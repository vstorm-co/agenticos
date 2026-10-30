//! Descriptor-relative filesystem access, anchored in an approved directory.
use std::io;
use std::path::{Component, Path, PathBuf};

use cap_fs_ext::{DirExt, OpenOptionsSyncExt};
use cap_std::fs::{Dir, File, OpenOptions};

/// Open every component without following links, including the grant itself.
/// Tool calls can rename directories concurrently; a canonical path is not a lock.
pub fn open(root: &Path) -> io::Result<Dir> {
    if !root.is_absolute() {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "An absolute granted folder is required.",
        ));
    }
    let boundary = root.ancestors().last().ok_or_else(denied)?;
    let mut dir = Dir::open_ambient_dir(boundary, cap_std::ambient_authority())?;
    for component in root.strip_prefix(boundary).map_err(|_| denied())?.components() {
        match component {
            Component::Normal(name) => dir = dir.open_dir_nofollow(name)?,
            Component::CurDir => {}
            _ => return Err(denied()),
        }
    }
    Ok(dir)
}

/// Absolute paths may name this grant only; relative paths cannot climb above it.
pub fn relative(root: &Path, requested: &str) -> io::Result<PathBuf> {
    let asked = Path::new(requested);
    let path = if asked.is_absolute() {
        asked.strip_prefix(root).map_err(|_| denied())?
    } else {
        asked
    };
    let mut result = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Normal(name) => result.push(name),
            Component::CurDir => {}
            Component::ParentDir if result.pop() => {}
            _ => return Err(denied()),
        }
    }
    if result.as_os_str().is_empty() {
        result.push(".");
    }
    Ok(result)
}

/// Refuse devices and FIFOs on the opened handle, without waiting for a pipe writer.
pub fn regular(directory: &Dir, path: &Path, write: bool) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.nonblock(true);
    if write {
        options.write(true).create(true);
    } else {
        options.read(true);
    }
    let file = directory.open_with(path, &options)?;
    if !file.metadata()?.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "Only regular files can be opened.",
        ));
    }
    Ok(file)
}

fn denied() -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        "The path is outside the approved folder.",
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paths_cannot_leave_the_granted_folder() {
        let root = std::env::temp_dir().join("approved");
        assert_eq!(relative(&root, "a/../b").unwrap(), Path::new("b"));
        assert_eq!(
            relative(&root, &root.join("b").to_string_lossy()).unwrap(),
            Path::new("b")
        );
        for path in ["..", "a/../../outside"] {
            assert!(relative(&root, path).is_err());
        }
        assert!(relative(&root, &root.with_file_name("elsewhere").to_string_lossy()).is_err());
        assert!(open(Path::new("relative")).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn replacing_the_grant_with_a_symlink_is_refused() {
        let base = std::env::temp_dir().join(format!("agenticos-root-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(base.join("outside")).unwrap();
        std::os::unix::fs::symlink(base.join("outside"), base.join("granted")).unwrap();
        assert!(open(&base.join("granted")).is_err());
        std::fs::remove_dir_all(base).unwrap();
    }
}
