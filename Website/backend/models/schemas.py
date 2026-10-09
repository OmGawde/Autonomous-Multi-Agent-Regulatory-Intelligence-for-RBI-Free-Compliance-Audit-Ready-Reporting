from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from datetime import datetime, date
from typing import TypedDict, Optional, List, Dict, Union, Any

# --- API Request/Response Schemas ---

class UploadRequest(BaseModel):
    applicant_name: str
    bank_name: str

class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: Union[UUID, str]
    applicant_name: str
    bank_name: str
    status: str
    file_path: Optional[str] = None
    created_at: Union[datetime, str]

class TransactionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # `id` was previously dropped by this schema, leaving the front-end table
    # keyed on the array index with no stable row identity.
    id: Optional[str] = None
    date: Optional[Any] = ""
    description: Optional[str] = ""
    debit: Optional[float] = 0.0
    credit: Optional[float] = 0.0
    balance: Optional[float] = 0.0

    # Classification, merged in from the pipeline's classified output.
    # transaction_records itself stores none of this, so without the merge the
    # UI has no counterparty to tag and no label to show.
    category: Optional[str] = None
    subcategory: Optional[str] = None
    needs_wants: Optional[str] = None
    counterparty_key: Optional[str] = None
    classification_method: Optional[str] = None
    recurrence_type: Optional[str] = None
    suggestion_reason: Optional[str] = None

class LoanResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_id: Union[UUID, str]
    # Optional because the pipeline now reports a value as genuinely unavailable
    # rather than substituting a plausible number (e.g. DTI when income could
    # not be determined). The UI must render these as "Not available", not 0.
    average_monthly_balance: Optional[float] = None
    total_income: Optional[float] = None
    total_expenses: Optional[float] = None
    debt_to_income_ratio: Optional[float] = None
    monthly_obligations: Optional[float] = None
    decision: str
    confidence_score: Optional[float] = None
    reasoning: str
    created_at: Union[datetime, str]

    # The full engine feature bundle. It was always written to the database but
    # never declared here, so Pydantic silently dropped ~26KB of features on
    # every response -- which is why the front-end's engine cards rendered zeros
    # while reporting the engines as ACTIVE.
    bank_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    loan_eligibility: Optional[Dict[str, Any]] = None
    audit_verification: Optional[Dict[str, Any]] = None

class StatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    application_id: Union[UUID, str]
    status: str
    message: str
    progress: Optional[int] = 0
    applicant_name: Optional[str] = None
    bank_name: Optional[str] = None

class BanksListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    banks: List[str]

class ApplicationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: Union[UUID, str]
    applicant_name: str
    bank_name: str
    status: str
    created_at: Union[datetime, str]
    decision: Optional[str] = None
    confidence_score: Optional[float] = None
    average_monthly_balance: Optional[float] = None

class ApplicationsListResponse(BaseModel):
    applications: List[ApplicationListItem]

class TransactionsResponse(BaseModel):
    transactions: List[TransactionSchema]

class CopilotQueryRequest(BaseModel):
    application_id: str
    question: str

class CopilotCitation(BaseModel):
    date: Optional[str] = None
    narration: Optional[str] = None
    amount: Optional[float] = 0.0
    lender: Optional[str] = None

class CopilotQueryResponse(BaseModel):
    answer: str
    citations: List[Dict[str, Any]] = []

# --- LangGraph Pipeline State ---

class PipelineState(TypedDict):
    application_id: str
    file_path: str
    bank_name: str
    column_mapping: Dict[str, str]
    transactions: List[Dict]
    extraction_status: str
    error_message: Optional[str]
    analysis: Dict
    loan_result: Dict
    pdf_type: Optional[str]              # 'digital' or 'scanned'
    explicit_vertical_lines: Optional[List[float]]  # X coords from calibration tool
