//! Private, checksummed Node and a locked adapter tree; no host npm or Node needed.
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const NODE_VERSION: &str = "24.19.0";
const MANIFEST: &str = include_str!("../../runtime/package.json");
const LOCK: &str = include_str!("../../runtime/package-lock.json");
static PREPARING: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

pub struct Runtime {
    pub node: PathBuf,
    pub directory: PathBuf,
}

impl Runtime {
    pub fn adapter(&self, agent: crate::local_agents::AgentId) -> PathBuf {
        self.directory
            .join("node_modules/@agentclientprotocol")
            .join(match agent {
                crate::local_agents::AgentId::ClaudeCode => "claude-agent-acp/dist/index.js",
                crate::local_agents::AgentId::Codex => "codex-acp/dist/index.js",
            })
    }
    pub fn cli(&self, agent: crate::local_agents::AgentId) -> Result<(PathBuf, Vec<String>), String> {
        match agent {
            crate::local_agents::AgentId::ClaudeCode => {
                let platform = match std::env::consts::OS {
                    "macos" => "darwin",
                    "windows" => "win32",
                    other => other,
                };
                let arch = match std::env::consts::ARCH {
                    "aarch64" => "arm64",
                    "x86_64" => "x64",
                    _ => return Err("Unsupported coding agent architecture.".into()),
                };
                let name = format!("@anthropic-ai/claude-agent-sdk-{platform}-{arch}");
                let binary = self.directory.join("node_modules").join(name).join(if cfg!(windows) {
                    "claude.exe"
                } else {
                    "claude"
                });
                if !binary.is_file() {
                    return Err("Claude Code was not installed completely. Retry preparing coding tools.".into());
                }
                Ok((binary, Vec::new()))
            }
            crate::local_agents::AgentId::Codex => Ok((
                self.node.clone(),
                vec![self
                    .directory
                    .join("node_modules/@openai/codex/bin/codex.js")
                    .to_string_lossy()
                    .into_owned()],
            )),
        }
    }
    pub fn command(&self) -> Result<tokio::process::Command, String> {
        let mut command = tokio::process::Command::new(&self.node);
        let parent = self
            .node
            .parent()
            .ok_or("The private runtime has no executable directory.")?;
        let inherited = std::env::var_os("PATH").unwrap_or_default();
        let path = std::env::join_paths(std::iter::once(parent.to_path_buf()).chain(std::env::split_paths(&inherited)))
            .map_err(|e| format!("Cannot prepare the coding runtime: {e}"))?;
        command.env("PATH", path).current_dir(&self.directory);
        Ok(command)
    }
}

fn release(os: &str, arch: &str) -> Result<(&'static str, &'static str), String> {
    match (os, arch) {
        ("macos", "aarch64") => Ok((
            "darwin-arm64.tar.gz",
            "8294b7aa9b03997481c06babf1e8b270c859358f27da57a11509afe537ac381d",
        )),
        ("macos", "x86_64") => Ok((
            "darwin-x64.tar.gz",
            "d1b5e999db158c62fe8f7267a4476b035d8bd93b1a605bac24a3f0dd166e3316",
        )),
        ("linux", "aarch64") => Ok((
            "linux-arm64.tar.gz",
            "d28c8a5bf0a808f0ed434a1dce8c54ae98f0371c0bd86ac58abc613f73e6643f",
        )),
        ("linux", "x86_64") => Ok((
            "linux-x64.tar.gz",
            "f625d97cd707df4ff96254916fbc5ff014f09c09effe5a1e0ca8f6d41a8789d4",
        )),
        ("windows", "aarch64") => Ok((
            "win-arm64.zip",
            "8502f4a50b458d4cc38ed8f2001556c2cd239d464920f74017926ccb1e1c157f",
        )),
        ("windows", "x86_64") => Ok((
            "win-x64.zip",
            "57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73",
        )),
        _ => Err("This computer's architecture is not supported by the coding runtime.".into()),
    }
}

fn root_name(archive: &str) -> String {
    format!(
        "node-v{NODE_VERSION}-{}",
        archive.trim_end_matches(".tar.gz").trim_end_matches(".zip")
    )
}

fn at(directory: PathBuf, archive: &str) -> Runtime {
    let root = directory.join(root_name(archive));
    Runtime {
        node: root.join(if cfg!(windows) { "node.exe" } else { "bin/node" }),
        directory,
    }
}

fn complete(runtime: &Runtime) -> bool {
    let present = |path: &Path| path.metadata().is_ok_and(|meta| meta.is_file() && meta.len() > 0);
    present(&runtime.node)
        && [
            crate::local_agents::AgentId::ClaudeCode,
            crate::local_agents::AgentId::Codex,
        ]
        .into_iter()
        .all(|agent| {
            present(&runtime.adapter(agent))
                && runtime.cli(agent).is_ok_and(|(program, args)| {
                    present(&program) && args.first().is_none_or(|path| present(Path::new(path)))
                })
        })
        && std::fs::read_to_string(runtime.directory.join("ready")).is_ok_and(|marker| marker == revision())
}

fn revision() -> String {
    format!(
        "{:x}",
        Sha256::digest(format!("{NODE_VERSION}\n{MANIFEST}\n{LOCK}").as_bytes())
    )
}

pub fn existing(app: &AppHandle) -> Result<Option<Runtime>, String> {
    let (archive, _) = release(std::env::consts::OS, std::env::consts::ARCH)?;
    let directory = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("coding-runtime")
        .join(revision());
    let runtime = at(directory, archive);
    Ok(complete(&runtime).then_some(runtime))
}

pub async fn prepare(app: &AppHandle) -> Result<Runtime, String> {
    let root = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("coding-runtime");
    prepare_at(&root).await
}

pub async fn run(mut command: tokio::process::Command, action: &str) -> Result<(), String> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let mut child = crate::local_work::spawn_tree(command).map_err(|e| format!("Cannot {action}: {}", e.message))?;
    let mut stderr = child
        .0
        .stderr()
        .take()
        .ok_or("The coding runtime did not provide its error output.")?;
    let completion = async {
        let read = async {
            let mut tail = Vec::new();
            (&mut stderr).take(256 * 1024).read_to_end(&mut tail).await?;
            tokio::io::copy(&mut stderr, &mut tokio::io::sink()).await?;
            Ok::<_, std::io::Error>(tail)
        };
        let (status, tail) = tokio::join!(child.0.wait(), read);
        let status = status.map_err(|e| format!("Cannot {action}: {e}"))?;
        tail.map_err(|e| format!("Cannot read {action} diagnostics: {e}"))?;
        if status.success() {
            Ok(())
        } else {
            Err(format!("Could not {action}. Check your connection and try again."))
        }
    };
    match tokio::time::timeout(Duration::from_secs(900), completion).await {
        Ok(result) => result,
        Err(_) => {
            let _ = child.0.start_kill();
            let _ = child.0.wait().await;
            Err(format!("Timed out while trying to {action}. Try again."))
        }
    }
}

async fn prepare_at(root: &Path) -> Result<Runtime, String> {
    let _preparing = PREPARING.lock().await;
    let (archive, checksum) = release(std::env::consts::OS, std::env::consts::ARCH)?;
    let destination = root.join(revision());
    let runtime = at(destination.clone(), archive);
    if complete(&runtime) {
        return Ok(runtime);
    }
    if destination.exists() {
        tokio::fs::rename(&destination, root.join(format!("incomplete-{}", uuid::Uuid::new_v4())))
            .await
            .map_err(|e| format!("Cannot repair coding tools: {e}"))?;
    }
    tokio::fs::create_dir_all(root).await.map_err(|e| e.to_string())?;
    let disk_path = root.to_path_buf();
    tauri::async_runtime::spawn_blocking(move || crate::local_preflight::disk(&disk_path))
        .await
        .map_err(|e| e.to_string())??;
    let pending = root.join(format!("pending-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir(&pending).await.map_err(|e| e.to_string())?;
    let result = install(&pending, archive, checksum).await;
    if let Err(error) = result {
        let _ = tokio::fs::remove_dir_all(&pending).await;
        return Err(error);
    }
    tokio::fs::rename(&pending, &destination)
        .await
        .map_err(|e| format!("Cannot finish preparing coding tools: {e}"))?;
    Ok(at(destination, archive))
}

async fn install(directory: &Path, archive: &str, checksum: &str) -> Result<(), String> {
    let name = format!("node-v{NODE_VERSION}-{archive}");
    let url = format!("https://nodejs.org/dist/v{NODE_VERSION}/{name}");
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(900))
        .connect_timeout(Duration::from_secs(20))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|e| e.to_string())?;
    let mut response = client
        .get(url)
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|e| format!("Cannot download coding tools: {e}"))?;
    let file = directory.join(&name);
    let mut output = tokio::fs::File::create(&file).await.map_err(|e| e.to_string())?;
    let mut hash = Sha256::new();
    let mut size = 0;
    while let Some(chunk) = response.chunk().await.map_err(|e| e.to_string())? {
        size += chunk.len();
        if size > 256 * 1024 * 1024 {
            return Err("The coding runtime download exceeded its size limit.".into());
        }
        hash.update(&chunk);
        output.write_all(&chunk).await.map_err(|e| e.to_string())?;
    }
    output.flush().await.map_err(|e| e.to_string())?;
    drop(output);
    if format!("{:x}", hash.finalize()) != checksum {
        return Err("The coding runtime failed its integrity check. Try downloading again.".into());
    }
    let mut extract = tokio::process::Command::new(if cfg!(windows) { "tar.exe" } else { "/usr/bin/tar" });
    extract.arg("-xf").arg(&file).arg("-C").arg(directory);
    run(extract, "unpack coding tools").await?;
    tokio::fs::remove_file(file).await.map_err(|e| e.to_string())?;
    tokio::fs::write(directory.join("package.json"), MANIFEST)
        .await
        .map_err(|e| e.to_string())?;
    tokio::fs::write(directory.join("package-lock.json"), LOCK)
        .await
        .map_err(|e| e.to_string())?;
    let config = directory.join("npmrc");
    tokio::fs::write(&config, "registry=https://registry.npmjs.org/\n")
        .await
        .map_err(|e| e.to_string())?;
    let runtime = at(directory.to_path_buf(), archive);
    let node_root = directory.join(root_name(archive));
    let npm = node_root.join(if cfg!(windows) {
        "node_modules/npm/bin/npm-cli.js"
    } else {
        "lib/node_modules/npm/bin/npm-cli.js"
    });
    let mut install = runtime.command()?;
    install
        .arg(npm)
        .args([
            "ci",
            "--ignore-scripts",
            "--include=optional",
            "--no-audit",
            "--no-fund",
        ])
        .env("NPM_CONFIG_USERCONFIG", config)
        .env("NPM_CONFIG_CACHE", directory.join("npm-cache"))
        .env("NPM_CONFIG_REGISTRY", "https://registry.npmjs.org/");
    run(install, "install coding tools").await?;
    for agent in [
        crate::local_agents::AgentId::ClaudeCode,
        crate::local_agents::AgentId::Codex,
    ] {
        if !runtime.adapter(agent).is_file() {
            return Err("A coding adapter was missing after installation.".into());
        }
        let (program, args) = runtime.cli(agent)?;
        let mut verify = tokio::process::Command::new(program);
        verify.args(args).arg("--version").current_dir(directory);
        run(verify, "verify coding tools").await?;
    }
    tokio::fs::write(directory.join("ready"), revision())
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn downloads_are_pinned_for_every_supported_platform() {
        for os in ["macos", "windows", "linux"] {
            for arch in ["aarch64", "x86_64"] {
                let (name, hash) = release(os, arch).unwrap();
                assert_eq!(hash.len(), 64);
                assert!(hash.bytes().all(|b| b.is_ascii_hexdigit()));
                assert!(!root_name(name).ends_with(".gz"));
            }
        }
        assert!(release("linux", "unknown").is_err());
        assert_eq!(revision().len(), 64);
        let lock: serde_json::Value = serde_json::from_str(LOCK).unwrap();
        for entry in lock["packages"].as_object().unwrap().values().skip(1) {
            assert!(entry["integrity"].as_str().is_some());
            assert!(entry["resolved"]
                .as_str()
                .unwrap()
                .starts_with("https://registry.npmjs.org/"));
        }
    }

    #[tokio::test]
    #[ignore = "Downloads the verified Node runtime and locked coding tools; run explicitly"]
    async fn clean_machine_prepares_without_host_node_or_npm() {
        let root = std::env::temp_dir().join(format!("agenticos-coding-smoke-{}", uuid::Uuid::new_v4()));
        let runtime = prepare_at(&root).await.unwrap();
        let mut command = runtime.command().unwrap();
        command.args(["-e", "if (process.versions.node !== '24.19.0') process.exit(1)"]);
        run(command, "check private Node").await.unwrap();
        for agent in [
            crate::local_agents::AgentId::ClaudeCode,
            crate::local_agents::AgentId::Codex,
        ] {
            let (program, prefix) = runtime.cli(agent).unwrap();
            let mut command = tokio::process::Command::new(program);
            command.args(prefix).arg("--version");
            run(command, "check prepared agent").await.unwrap();
            check_adapter(&runtime, agent).await;
        }
        let again = prepare_at(&root).await.unwrap();
        assert_eq!(runtime.node, again.node);
        tokio::fs::remove_dir_all(root).await.unwrap();
    }

    async fn check_adapter(runtime: &Runtime, agent: crate::local_agents::AgentId) {
        use tokio::io::{AsyncBufReadExt, BufReader};
        let mut command = runtime.command().unwrap();
        command
            .arg(runtime.adapter(agent))
            .env_remove("CODEX_PATH")
            .env_remove("CLAUDE_CODE_EXECUTABLE")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        let mut child = crate::local_work::spawn_tree(command).unwrap();
        let mut stdin = child.0.stdin().take().unwrap();
        let mut stdout = BufReader::new(child.0.stdout().take().unwrap()).lines();
        stdin.write_all(b"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":1,\"clientCapabilities\":{},\"clientInfo\":{\"name\":\"agenticos-smoke\",\"version\":\"1\"}}}\n").await.unwrap();
        let initialized = tokio::time::timeout(Duration::from_secs(45), async {
            while let Some(line) = stdout.next_line().await.unwrap() {
                let message: serde_json::Value = serde_json::from_str(&line).unwrap();
                if message["id"] == 1 {
                    return message["result"]["protocolVersion"] == 1;
                }
            }
            false
        })
        .await;
        child.0.start_kill().unwrap();
        child.0.wait().await.unwrap();
        assert_eq!(initialized, Ok(true), "{agent:?} did not initialize over ACP");
    }
}
