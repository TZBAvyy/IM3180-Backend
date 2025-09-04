from pydantic import BaseModel

# --- Error Models ---
# --- For Documentation Page ---

class HTTPError(BaseModel):
    detail: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Error message here"
            }
        }