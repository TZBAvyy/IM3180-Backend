from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.routes import trip_optimizer, cluster, multicluster, gemini, auth, trips_crud

# --- FastAPI main app code---

app = FastAPI(title="IM3180 API", version="1.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your frontend domain in prod
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trip_optimizer.router)
app.include_router(cluster.router)
app.include_router(multicluster.router)
app.include_router(gemini.router)
app.include_router(auth.router)
app.include_router(trips_crud.router)

@app.get("/")
def test():
    return {"success": True,"project": "IM3180-IE04-AY2526"}
