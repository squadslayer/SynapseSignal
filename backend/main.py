from fastapi import FastAPI
from backend.api import ingest, state

app = FastAPI()

app.include_router(ingest.router)
app.include_router(state.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
