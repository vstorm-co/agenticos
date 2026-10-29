//! Fixed, navigation-only links from the macOS widget. They never open a microphone.
use tauri::{AppHandle, Url};

#[derive(Debug, PartialEq, Eq)]
enum Destination {
    QuickAsk,
    Console(&'static str),
}

fn destination(url: &Url) -> Option<Destination> {
    if url.scheme() != "agenticos"
        || url.host_str() != Some("widget")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.port().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return None;
    }
    match url.path() {
        "/quick-ask" => Some(Destination::QuickAsk),
        "/chat" => Some(Destination::Console("/chat")),
        "/inbox" => Some(Destination::Console("/inbox")),
        "/activity" => Some(Destination::Console("/runs")),
        _ => None,
    }
}

pub fn handle(app: &AppHandle, url: &Url) -> Result<bool, String> {
    let Some(destination) = destination(url) else {
        return Ok(false);
    };
    let settings = crate::settings::current(app);
    if settings.server_url.is_none() {
        crate::bring_console(app)?;
        return Ok(true);
    }
    match destination {
        Destination::QuickAsk => {
            crate::quick_ask::show(app, settings.server_url.as_ref(), settings.appearance)?;
        }
        Destination::Console(path) => crate::open_in_console_at(app, path)?,
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::{destination, Destination};
    use tauri::Url;

    #[test]
    fn widget_links_open_only_fixed_application_pages() {
        assert_eq!(
            destination(&Url::parse("agenticos://widget/quick-ask").unwrap()),
            Some(Destination::QuickAsk)
        );
        assert_eq!(
            destination(&Url::parse("agenticos://widget/chat").unwrap()),
            Some(Destination::Console("/chat"))
        );
        assert_eq!(
            destination(&Url::parse("agenticos://widget/inbox").unwrap()),
            Some(Destination::Console("/inbox"))
        );
        assert_eq!(
            destination(&Url::parse("agenticos://widget/activity").unwrap()),
            Some(Destination::Console("/runs"))
        );
        for value in [
            "https://widget/chat",
            "agenticos://widget/chat?start=call",
            "agenticos://widget/call",
            "agenticos://widget/chat#call",
            "agenticos://person@widget/chat",
            "agenticos://widget/chat/elsewhere",
        ] {
            assert_eq!(destination(&Url::parse(value).unwrap()), None);
        }
    }
}
