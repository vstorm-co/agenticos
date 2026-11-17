# IMAP mail

Read a fixed mailbox through a personal or organization account. Credentials
are vault-sealed with their destination; the host must be explicitly allowed
in MIRAGE_ALLOWED_HOSTS. TLS is mandatory. Searches and BODY.PEEK reads never
mark mail as read. Watches use UIDVALIDITY and the last consumed UID; a reset
establishes a quiet baseline. The protocol and MIME parser are Mirage's.
