//! A file dropped on blobby or on the Dock icon (#2305): a new chat, with it
//! attached.
//!
//! The shell holds the paths it was handed - those, and nothing else - until
//! the console takes them with `take_shared`. That is the command the phone app
//! answers with what another app shared with it, and the answer has the same
//! shape, so the console makes the same new chat of either: the console is a
//! page of a server, and must not be able to ask the shell for any other path.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use base64::Engine;
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

/// What the console listens for: something was dropped, take it.
pub const EVENT: &str = "desktop:dropped";
/// A file larger than this is named, not read - the chat's own ceiling.
const MAX_FILE_BYTES: u64 = 20 * 1024 * 1024;
/// A drop of a whole folder's worth is a file transfer, not a message.
const MAX_FILES: usize = 10;

/// The paths dropped since the console last took them.
#[derive(Default)]
pub struct Dropped(Mutex<Vec<PathBuf>>);

/// What was dropped, as the console reads `take_shared`'s answer.
#[derive(Serialize, Default, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Shared {
    pub text: String,
    pub files: Vec<SharedFile>,
    /// Files that could not be carried over - too large, unreadable, one too
    /// many - by name, for the console to say so.
    pub refused: Vec<String>,
}

#[derive(Serialize, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SharedFile {
    pub name: String,
    pub mime_type: String,
    /// The file's bytes, base64.
    pub data: String,
}

/// Files dropped: held, the console brought forward, and told.
pub fn receive(app: &AppHandle, paths: Vec<PathBuf>) {
    let files: Vec<PathBuf> = paths.into_iter().filter(|path| path.is_file()).collect();
    if files.is_empty() {
        return;
    }
    if let Ok(mut held) = app.state::<Dropped>().0.lock() {
        held.extend(files);
    }
    // A console that is not open yet takes them when it arrives; one that is
    // hears the event.
    if let Err(e) = crate::bring_console(app) {
        eprintln!("{e}");
    }
    if let Err(e) = app.emit_to(crate::WINDOW, EVENT, ()) {
        eprintln!("{e}");
    }
}

/// What was dropped since the last time, read now and forgotten after; `None`
/// when nothing was.
#[tauri::command]
pub fn take_shared(app: AppHandle) -> Result<Option<Shared>, String> {
    let paths = app
        .state::<Dropped>()
        .0
        .lock()
        .map(|mut held| std::mem::take(&mut *held))
        .map_err(|e| e.to_string())?;
    Ok(collect(&paths))
}

fn collect(paths: &[PathBuf]) -> Option<Shared> {
    if paths.is_empty() {
        return None;
    }
    let mut shared = Shared::default();
    for (index, path) in paths.iter().enumerate() {
        match (index < MAX_FILES).then(|| read(path)) {
            Some(Some(file)) => shared.files.push(file),
            _ => shared.refused.push(name_of(path)),
        }
    }
    Some(shared)
}

fn name_of(path: &Path) -> String {
    path.file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// The file, or `None` when it is too large or cannot be read.
fn read(path: &Path) -> Option<SharedFile> {
    if std::fs::metadata(path).ok()?.len() > MAX_FILE_BYTES {
        return None;
    }
    let bytes = std::fs::read(path).ok()?;
    // What the bytes say they are, so a picture is previewed as one; anything
    // else is left to the server, which reads the type from the extension.
    let mime_type = infer::get(&bytes)
        .map(|kind| kind.mime_type())
        .unwrap_or("application/octet-stream")
        .to_owned();
    Some(SharedFile {
        name: name_of(path),
        mime_type,
        data: base64::engine::general_purpose::STANDARD.encode(bytes),
    })
}

#[cfg(test)]
mod tests {
    use super::{collect, MAX_FILES};

    #[test]
    fn nothing_dropped_is_nothing_to_take() {
        assert_eq!(collect(&[]), None);
    }

    #[test]
    fn a_drop_is_read_whole_and_what_cannot_be_is_named() {
        let dir = std::env::temp_dir().join(format!("agenticos-dropped-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let note = dir.join("note.txt");
        std::fs::write(&note, "hello").unwrap();
        let picture = dir.join("dot.png");
        std::fs::write(&picture, b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR").unwrap();

        let shared = collect(&[note.clone(), picture, dir.join("gone.pdf")]).unwrap();

        assert_eq!(shared.files.len(), 2);
        assert_eq!(shared.files[0].name, "note.txt");
        assert_eq!(shared.files[0].data, "aGVsbG8=");
        assert_eq!(shared.files[0].mime_type, "application/octet-stream");
        assert_eq!(shared.files[1].mime_type, "image/png");
        assert_eq!(shared.refused, vec!["gone.pdf".to_owned()]);

        let many: Vec<_> = (0..=MAX_FILES).map(|_| note.clone()).collect();
        let shared = collect(&many).unwrap();
        assert_eq!(shared.files.len(), MAX_FILES);
        assert_eq!(shared.refused, vec!["note.txt".to_owned()]);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn it_reaches_the_console_in_the_shape_the_phone_app_answers_with() {
        let shared = super::Shared {
            files: vec![super::SharedFile {
                name: "a.pdf".into(),
                mime_type: "application/pdf".into(),
                data: String::new(),
            }],
            ..Default::default()
        };
        let json = serde_json::to_value(&shared).unwrap();
        assert_eq!(json["files"][0]["mimeType"], "application/pdf");
        assert_eq!(json["text"], "");
        assert_eq!(json["refused"], serde_json::json!([]));
    }
}
