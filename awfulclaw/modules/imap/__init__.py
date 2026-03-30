from awfulclaw.modules.base import Module
from awfulclaw.modules.imap._imap import EmailSummary, ImapModule, fetch_unread

__all__ = ["EmailSummary", "ImapModule", "fetch_unread"]


def create_module() -> Module:
    return ImapModule()
