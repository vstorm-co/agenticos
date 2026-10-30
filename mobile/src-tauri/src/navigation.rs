//! A failed WebKit navigation never sends `PageLoadEvent::Finished`. Keep a
//! bounded wait so a saved, unavailable server cannot strand the phone on white.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};

#[derive(Default)]
pub struct Navigation {
    pending: Mutex<Option<Pending>>,
    pub notice: Mutex<Option<String>>,
}

struct Pending {
    active: Arc<AtomicBool>,
    // Dropping this sender wakes the waiting thread immediately.
    _cancel: Sender<()>,
}

impl Drop for Pending {
    fn drop(&mut self) {
        self.active.store(false, Ordering::SeqCst);
    }
}

pub struct Attempt {
    active: Arc<AtomicBool>,
    pub cancelled: Receiver<()>,
}

impl Attempt {
    /// Checked again on the UI thread: a page may have finished since the
    /// timeout queued its recovery, or a newer navigation may have replaced it.
    pub fn claim(&self) -> bool {
        self.active.swap(false, Ordering::SeqCst)
    }
}

impl Navigation {
    pub fn begin(&self) -> Result<Attempt, String> {
        let mut pending = self.pending.lock().map_err(|e| e.to_string())?;
        let (cancel, cancelled) = mpsc::channel();
        let active = Arc::new(AtomicBool::new(true));
        *pending = Some(Pending {
            active: active.clone(),
            _cancel: cancel,
        });
        Ok(Attempt { active, cancelled })
    }

    pub fn finish(&self) -> Result<(), String> {
        self.pending.lock().map_err(|e| e.to_string())?.take();
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::Navigation;
    use std::sync::mpsc::RecvTimeoutError;
    use std::time::Duration;

    #[test]
    fn a_finished_or_replaced_load_cannot_recover_over_a_working_page() {
        let navigation = Navigation::default();
        let first = navigation.begin().unwrap();
        let second = navigation.begin().unwrap();
        assert!(!first.claim());
        assert_eq!(
            first.cancelled.recv_timeout(Duration::ZERO),
            Err(RecvTimeoutError::Disconnected)
        );
        navigation.finish().unwrap();
        assert!(!second.claim());
        assert_eq!(
            second.cancelled.recv_timeout(Duration::ZERO),
            Err(RecvTimeoutError::Disconnected)
        );
    }

    #[test]
    fn only_a_pending_attempt_can_recover_and_only_once() {
        let navigation = Navigation::default();
        let attempt = navigation.begin().unwrap();
        assert_eq!(
            attempt.cancelled.recv_timeout(Duration::ZERO),
            Err(RecvTimeoutError::Timeout)
        );
        assert!(attempt.claim());
        assert!(!attempt.claim());
    }

    #[test]
    fn dropping_the_window_state_cancels_its_waiter() {
        let navigation = Navigation::default();
        let attempt = navigation.begin().unwrap();
        drop(navigation);
        assert!(!attempt.claim());
        assert_eq!(
            attempt.cancelled.recv_timeout(Duration::ZERO),
            Err(RecvTimeoutError::Disconnected)
        );
    }
}
