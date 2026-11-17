# Google Docs

Calls the product API through a connected account. Each operation is declared
in `services/integrations/catalog.py` and reused by workflow nodes. Personal
accounts resolve from the run's person; organization accounts are bound by id.
Tokens stay in the vault. Writes require interactive approval.
