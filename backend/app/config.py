from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')


@dataclass
class Settings:
    database_url: str = os.getenv('DATABASE_URL', f'sqlite:///{(ROOT / ".data" / "fdr.db").as_posix()}')
    storage_dir: Path = Path(os.getenv('STORAGE_DIR', str(ROOT / '.data' / 'documents'))).resolve()
    api_key: str = os.getenv('API_KEY', 'local-demo-key')
    frontend_origins: str = os.getenv('FRONTEND_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173')
    extraction_mode: str = os.getenv('EXTRACTION_MODE', 'demo')
    gemma_base_url: str = os.getenv('GEMMA_BASE_URL', '')
    gemma_model: str = os.getenv('GEMMA_MODEL', '')
    gemma_api_key: str = os.getenv('GEMMA_API_KEY', '')
    gemma_timeout: float = float(os.getenv('GEMMA_TIMEOUT_SECONDS', '45'))
    max_upload_mb: int = int(os.getenv('MAX_UPLOAD_MB', '10'))
    max_pages: int = int(os.getenv('MAX_DOCUMENT_PAGES', '30'))
    minimum_amount: Decimal = Decimal(os.getenv('MINIMUM_AMOUNT', '10000'))
    currency: str = os.getenv('DEFAULT_CURRENCY', 'INR')
    reminder_days: int = int(os.getenv('REMINDER_DAYS', '30'))
    ocr_enabled: bool = os.getenv('OCR_ENABLED', 'false').lower() == 'true'
    required_fields: str = os.getenv('REQUIRED_FIELDS', 'instrument_number,bank_name,amount,currency,issue_date,maturity_date,holder_name')
    disabled_rules: str = os.getenv('DISABLED_RULES', '')

    def __post_init__(self):
        if not self.api_key.strip():
            raise ValueError('API_KEY must not be empty')
        if self.extraction_mode not in ('demo', 'gemma'):
            raise ValueError('EXTRACTION_MODE must be demo or gemma')
        if self.minimum_amount < 0 or not self.minimum_amount.is_finite():
            raise ValueError('MINIMUM_AMOUNT must be a finite positive decimal')
        if self.max_upload_mb < 1 or self.max_pages < 1 or self.reminder_days < 0:
            raise ValueError('File, page and reminder limits are invalid')
