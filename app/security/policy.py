ALLOWED_TOOLS = frozenset({"current_time", "current_date", "battery_status", "storage_status", "open_application", "open_url", "search_google", "help"})
ALLOWED_APPLICATIONS = frozenset({"chrome", "spotify", "settings", "notepad", "word", "calculator", "vscode", "file_explorer"})
ALLOWED_URLS = {"chatgpt": "https://chatgpt.com", "google": "https://www.google.com"}

from app.security.filesystem_policy import FILESYSTEM_TOOLS
ALLOWED_TOOLS = ALLOWED_TOOLS | FILESYSTEM_TOOLS
from app.documents.policy import DOCUMENT_TOOLS
ALLOWED_TOOLS = ALLOWED_TOOLS | DOCUMENT_TOOLS
from app.projects.policy import PROJECT_TOOLS
ALLOWED_TOOLS = ALLOWED_TOOLS | PROJECT_TOOLS
CONFIRMATION_REQUIRED_TOOLS = frozenset({"create_folder", "start_project", "stop_project"})
from app.knowledge.policy import KNOWLEDGE_TOOLS
ALLOWED_TOOLS = ALLOWED_TOOLS | KNOWLEDGE_TOOLS
CONFIRMATION_REQUIRED_TOOLS = CONFIRMATION_REQUIRED_TOOLS | {'remove_indexed_document', 'clear_document_index'}
