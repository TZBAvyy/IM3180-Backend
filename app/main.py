from fastapi import FastAPI
from app.routes import trip_optimizer, cluster, gemini

# --- FastAPI main app code---

app = FastAPI()

app.include_router(trip_optimizer.router)
app.include_router(cluster.router)
app.include_router(gemini.router)


@app.get("/test")
def test():
    return {"success": True,"project": "IM3180-IE04-AY2526"}
