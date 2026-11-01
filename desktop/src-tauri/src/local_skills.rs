//! The skills and project instructions already on this computer (#2576).
//!
//! A person who uses Claude Code or Codex has skills in `~/.claude/skills`,
//! `~/.codex/skills` and `~/.agents/skills`, and an `AGENTS.md` that says how they
//! like to work. When a chat asks for them, the server reads them *through this
//! module*, in place: nothing is copied into AgenticOS, nothing is written, and
//! only what the chat's sources name is looked at. The files are the person's;
//! this module lists, reads and confines.
//!
//! Where the same skill name appears in more than one source, `.agents` wins over
//! `.claude`, which wins over `.codex`, and the shadowed copy is reported rather
//! than dropped silently. A skill reached through two links to one folder is one
//! skill, not a shadow.

use std::collections::{HashMap, HashSet};
use std::io::Read;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tauri::AppHandle;

use crate::local_work::{self, Mode, Refusal};

/// The places skills live, in the order that settles a clash.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    Agents,
    Claude,
    Codex,
}

const PRECEDENCE: [Source; 3] = [Source::Agents, Source::Claude, Source::Codex];

impl Source {
    fn directory(self) -> &'static str {
        match self {
            Source::Agents => ".agents",
            Source::Claude => ".claude",
            Source::Codex => ".codex",
        }
    }
}

const MAX_SKILLS: usize = 300;
const MAX_DESCRIPTION: usize = 300;
/// A `SKILL.md` or `AGENTS.md` is read up to this; the rest is cut with a note.
const TEXT_LIMIT: u64 = 64 << 10;
/// A file inside a skill, such as a script or a reference.
const RESOURCE_LIMIT: u64 = 256 << 10;

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct Skill {
    pub name: String,
    pub description: String,
    pub source: Source,
    /// The source whose skill of the same name this one lost to, if it lost.
    pub shadowed_by: Option<Source>,
}

struct Found {
    skill: Skill,
    directory: PathBuf,
}

/// A name a model can load by: what a skill folder is called in practice.
fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        && !name.starts_with('.')
}

fn clip(text: &str, limit: usize) -> String {
    let line = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if line.chars().count() <= limit {
        line
    } else {
        format!("{}…", line.chars().take(limit - 1).collect::<String>())
    }
}

/// `name` and `description` from a `SKILL.md`'s front matter: the plain `key: value`
/// lines and the folded or literal block (`>`, `|`) a description is often written as.
fn front_matter(text: &str) -> HashMap<String, String> {
    let mut found = HashMap::new();
    let mut lines = text.lines();
    if lines.next().map(str::trim) != Some("---") {
        return found;
    }
    let mut key: Option<String> = None;
    for line in lines {
        if line.trim() == "---" {
            break;
        }
        let indented = line.starts_with(' ') || line.starts_with('\t');
        if let (true, Some(open)) = (indented, key.as_ref()) {
            let entry = found.entry(open.clone()).or_insert_with(String::new);
            if !entry.is_empty() {
                entry.push(' ');
            }
            entry.push_str(line.trim());
        } else if let Some((name, value)) = line.split_once(':') {
            let value = value.trim();
            let value = if matches!(value, ">" | "|" | ">-" | "|-") {
                ""
            } else {
                value
            };
            let value = value.trim_matches(|c| c == '"' || c == '\'');
            key = Some(name.trim().to_owned());
            found.insert(name.trim().to_owned(), value.to_owned());
        }
    }
    found
}

fn read_text(path: &Path, limit: u64) -> std::io::Result<String> {
    let mut data = Vec::new();
    std::fs::File::open(path)?.take(limit + 1).read_to_end(&mut data)?;
    let cut = data.len() as u64 > limit;
    data.truncate(limit as usize);
    let mut text = String::from_utf8_lossy(&data).into_owned();
    if cut {
        text.push_str("\n\n[Cut here: the file is longer than the app reads.]");
    }
    Ok(text)
}

/// Every skill in the enabled sources, a clash settled by precedence.
fn discover(home: &Path, enabled: &[Source]) -> Vec<Found> {
    let mut by_name: HashMap<String, usize> = HashMap::new();
    let mut seen_directories: HashSet<PathBuf> = HashSet::new();
    let mut all: Vec<Found> = Vec::new();
    for source in PRECEDENCE.into_iter().filter(|source| enabled.contains(source)) {
        let Ok(entries) = std::fs::read_dir(home.join(source.directory()).join("skills")) else {
            continue;
        };
        let mut folders: Vec<_> = entries.flatten().map(|entry| entry.path()).collect();
        folders.sort();
        for folder in folders {
            // A link into another source's folder is that skill, reached twice.
            let Ok(canonical) = std::fs::canonicalize(&folder) else {
                continue;
            };
            let manifest = canonical.join("SKILL.md");
            if !manifest.is_file() || !seen_directories.insert(canonical.clone()) {
                continue;
            }
            let Ok(text) = read_text(&manifest, TEXT_LIMIT) else {
                continue;
            };
            let meta = front_matter(&text);
            let fallback = folder
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default();
            let name = meta.get("name").filter(|n| !n.is_empty()).cloned().unwrap_or(fallback);
            if !valid_name(&name) || all.len() >= MAX_SKILLS {
                continue;
            }
            let description = clip(meta.get("description").map_or("", String::as_str), MAX_DESCRIPTION);
            if let Some(&winner) = by_name.get(&name) {
                let shadowed_by = Some(all[winner].skill.source);
                all.push(Found {
                    skill: Skill {
                        name,
                        description,
                        source,
                        shadowed_by,
                    },
                    directory: canonical,
                });
            } else {
                by_name.insert(name.clone(), all.len());
                all.push(Found {
                    skill: Skill {
                        name,
                        description,
                        source,
                        shadowed_by: None,
                    },
                    directory: canonical,
                });
            }
        }
    }
    all
}

fn home() -> Result<PathBuf, Refusal> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .ok_or_else(|| Refusal::new("denied", "This computer has no home folder."))
}

fn sources(args: &Map<String, Value>) -> Result<Vec<Source>, Refusal> {
    serde_json::from_value(args.get("sources").cloned().unwrap_or(Value::Null))
        .map_err(|_| Refusal::new("denied", "Name the skill sources to use."))
}

fn object(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

/// The skills a chat's sources offer, for the person to see and the model to choose from.
#[tauri::command]
pub fn local_skills(sources: Vec<Source>) -> Result<Vec<Skill>, String> {
    let home = home().map_err(|r| r.message)?;
    Ok(discover(&home, &sources).into_iter().map(|found| found.skill).collect())
}

fn list(args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let skills: Vec<Skill> = discover(&home()?, &sources(args)?)
        .into_iter()
        .map(|found| found.skill)
        .filter(|skill| skill.shadowed_by.is_none())
        .collect();
    Ok(object(serde_json::json!({ "skills": skills })))
}

/// A skill's `SKILL.md`, or one file inside its folder, read in place.
fn read(args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let name = args.get("name").and_then(Value::as_str).unwrap_or_default();
    let found = discover(&home()?, &sources(args)?)
        .into_iter()
        .find(|found| found.skill.name == name && found.skill.shadowed_by.is_none())
        .ok_or_else(|| Refusal::new("not_found", format!("No local skill is called {name}.")))?;
    let Some(file) = args.get("file").and_then(Value::as_str) else {
        let text =
            read_text(&found.directory.join("SKILL.md"), TEXT_LIMIT).map_err(|e| Refusal::new("io", e.to_string()))?;
        return Ok(object(serde_json::json!({ "text": text })));
    };
    let directory = crate::local_fs::open(&found.directory).map_err(|e| Refusal::new("denied", e.to_string()))?;
    let relative =
        crate::local_fs::relative(&found.directory, file).map_err(|e| Refusal::new("denied", e.to_string()))?;
    let handle =
        crate::local_fs::regular(&directory, &relative, false).map_err(|e| Refusal::new("not_found", e.to_string()))?;
    let mut data = Vec::new();
    handle
        .take(RESOURCE_LIMIT + 1)
        .read_to_end(&mut data)
        .map_err(|e| Refusal::new("io", e.to_string()))?;
    if data.len() as u64 > RESOURCE_LIMIT {
        return Err(Refusal::new(
            "denied",
            "That file is larger than the app reads from a skill.",
        ));
    }
    let text = String::from_utf8(data).map_err(|_| Refusal::new("denied", "That file is not text."))?;
    Ok(object(serde_json::json!({ "text": text })))
}

/// The newer of the two global `AGENTS.md` files, `~/.codex` or `~/.claude`.
fn global_instructions(home: &Path) -> Option<(Source, String)> {
    let newest = [Source::Codex, Source::Claude]
        .into_iter()
        .filter_map(|source| {
            let path = home.join(source.directory()).join("AGENTS.md");
            let modified = std::fs::metadata(&path).ok()?.modified().ok()?;
            Some((modified, source, path))
        })
        .max_by_key(|(modified, ..)| *modified)?;
    let (_, source, path) = newest;
    let text = read_text(&path, TEXT_LIMIT).ok()?;
    (!text.trim().is_empty()).then_some((source, text))
}

async fn instructions(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    let global = global_instructions(&home()?);
    // Only a folder the person granted, read through the same confinement as any file.
    let folder = match args.get("root").and_then(Value::as_str) {
        Some(root) => {
            let granted = local_work::granted_folder(app, root, Mode::ReadOnly)?;
            let path = granted.clone();
            tauri::async_runtime::spawn_blocking(move || {
                let directory = crate::local_fs::open(&path).ok()?;
                let relative = crate::local_fs::relative(&path, "AGENTS.md").ok()?;
                let file = crate::local_fs::regular(&directory, &relative, false).ok()?;
                let mut data = Vec::new();
                file.take(TEXT_LIMIT + 1).read_to_end(&mut data).ok()?;
                data.truncate(TEXT_LIMIT as usize);
                let text = String::from_utf8_lossy(&data).into_owned();
                (!text.trim().is_empty()).then_some(text)
            })
            .await
            .map_err(|e| Refusal::new("io", e.to_string()))?
        }
        None => None,
    };
    Ok(object(serde_json::json!({
        "global": global.as_ref().map(|(source, text)| serde_json::json!({ "source": source, "text": text })),
        "folder": folder,
    })))
}

/// Run one `local.*` operation.
pub async fn run(app: &AppHandle, op: &str, args: &Map<String, Value>) -> Result<Map<String, Value>, Refusal> {
    match op {
        "local.skills" => list(args),
        "local.skill.read" => read(args),
        "local.instructions" => instructions(app, args).await,
        other => Err(Refusal::new("denied", format!("This app does not do {other}."))),
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    fn home() -> PathBuf {
        let dir = std::env::temp_dir().join(format!("agenticos-skills-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn skill(home: &Path, source: &str, folder: &str, manifest: &str) -> PathBuf {
        let dir = home.join(source).join("skills").join(folder);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("SKILL.md"), manifest).unwrap();
        dir
    }

    fn names(found: &[Found]) -> Vec<(String, Source, Option<Source>)> {
        found
            .iter()
            .map(|f| (f.skill.name.clone(), f.skill.source, f.skill.shadowed_by))
            .collect()
    }

    const ALL: [Source; 3] = [Source::Agents, Source::Claude, Source::Codex];

    #[test]
    fn front_matter_reads_plain_folded_and_quoted_values() {
        let meta = front_matter(
            "---\nname: pdf-tools\ndescription: >\n  Read and fill\n  PDF forms.\nlicense: \"MIT\"\n---\nbody",
        );
        assert_eq!(meta["name"], "pdf-tools");
        assert_eq!(meta["description"], "Read and fill PDF forms.");
        assert_eq!(meta["license"], "MIT");
        assert!(front_matter("no front matter").is_empty());
    }

    #[test]
    fn the_name_defaults_to_the_folder_and_a_bad_name_is_skipped() {
        let home = home();
        skill(&home, ".claude", "plain", "---\ndescription: No name given\n---\n");
        skill(&home, ".claude", "named", "---\nname: renamed\ndescription: d\n---\n");
        skill(&home, ".claude", "bad", "---\nname: ../escape\n---\n");
        skill(&home, ".claude", "spaced", "---\nname: has space\n---\n");
        let found = discover(&home, &ALL);
        let listed: Vec<_> = names(&found).into_iter().map(|(name, ..)| name).collect();
        assert_eq!(listed, vec!["renamed", "plain"]);
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn a_clash_goes_to_agents_then_claude_then_codex_and_names_the_loser() {
        let home = home();
        skill(
            &home,
            ".codex",
            "review",
            "---\nname: review\ndescription: codex\n---\n",
        );
        skill(
            &home,
            ".claude",
            "review",
            "---\nname: review\ndescription: claude\n---\n",
        );
        skill(
            &home,
            ".agents",
            "review",
            "---\nname: review\ndescription: agents\n---\n",
        );
        let found = discover(&home, &ALL);
        assert_eq!(
            names(&found),
            vec![
                ("review".into(), Source::Agents, None),
                ("review".into(), Source::Claude, Some(Source::Agents)),
                ("review".into(), Source::Codex, Some(Source::Agents)),
            ]
        );
        // Only the sources a chat enabled are looked at.
        let only_codex = discover(&home, &[Source::Codex]);
        assert_eq!(names(&only_codex), vec![("review".into(), Source::Codex, None)]);
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn two_links_to_one_folder_are_one_skill_not_a_shadow() {
        let home = home();
        let real = skill(&home, ".agents", "shared", "---\nname: shared\ndescription: one\n---\n");
        std::fs::create_dir_all(home.join(".claude/skills")).unwrap();
        symlink(&real, home.join(".claude/skills/shared")).unwrap();
        let found = discover(&home, &ALL);
        assert_eq!(names(&found), vec![("shared".into(), Source::Agents, None)]);
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn descriptions_are_clipped_and_the_count_is_bounded() {
        let home = home();
        let long = format!("---\nname: long\ndescription: {}\n---\n", "word ".repeat(200));
        skill(&home, ".agents", "long", &long);
        let found = discover(&home, &ALL);
        assert!(found[0].skill.description.chars().count() <= MAX_DESCRIPTION);
        assert!(found[0].skill.description.ends_with('…'));
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn a_skill_file_is_read_in_place_and_cannot_leave_its_folder() {
        let home = home();
        let dir = skill(&home, ".agents", "tools", "---\nname: tools\n---\nUse the script.");
        std::fs::create_dir_all(dir.join("scripts")).unwrap();
        std::fs::write(dir.join("scripts/run.sh"), "echo hi").unwrap();
        std::fs::write(home.join("secret.txt"), "token").unwrap();
        symlink(home.join("secret.txt"), dir.join("linked.txt")).unwrap();
        let found = discover(&home, &ALL).remove(0);
        let open = crate::local_fs::open(&found.directory).unwrap();
        let reach = |path: &str| {
            crate::local_fs::relative(&found.directory, path)
                .and_then(|relative| crate::local_fs::regular(&open, &relative, false))
        };
        assert!(reach("scripts/run.sh").is_ok());
        assert!(reach("../../../secret.txt").is_err());
        assert!(reach("/etc/passwd").is_err());
        assert!(reach("linked.txt").is_err());
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn the_newer_global_agents_file_wins_and_an_empty_one_is_nothing() {
        let home = home();
        std::fs::create_dir_all(home.join(".codex")).unwrap();
        std::fs::create_dir_all(home.join(".claude")).unwrap();
        std::fs::write(home.join(".codex/AGENTS.md"), "codex rules").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(30));
        std::fs::write(home.join(".claude/AGENTS.md"), "claude rules").unwrap();
        assert_eq!(
            global_instructions(&home),
            Some((Source::Claude, "claude rules".into()))
        );
        std::thread::sleep(std::time::Duration::from_millis(30));
        std::fs::write(home.join(".codex/AGENTS.md"), "newer codex rules").unwrap();
        assert_eq!(
            global_instructions(&home),
            Some((Source::Codex, "newer codex rules".into()))
        );
        std::fs::write(home.join(".codex/AGENTS.md"), "   \n").unwrap();
        assert_eq!(global_instructions(&home), None);
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn a_long_instruction_file_is_cut_with_a_note() {
        let home = home();
        let path = home.join("AGENTS.md");
        std::fs::write(&path, "x".repeat(TEXT_LIMIT as usize + 100)).unwrap();
        let text = read_text(&path, TEXT_LIMIT).unwrap();
        assert!(text.ends_with("longer than the app reads.]"));
        std::fs::remove_dir_all(home).unwrap();
    }

    #[test]
    fn only_named_sources_parse() {
        let parse = |value: Value| sources(&object(serde_json::json!({ "sources": value })));
        assert_eq!(
            parse(serde_json::json!(["agents", "codex"])).unwrap(),
            vec![Source::Agents, Source::Codex]
        );
        assert!(parse(serde_json::json!(["/etc"])).is_err());
        assert!(sources(&Map::new()).is_err());
    }
}
