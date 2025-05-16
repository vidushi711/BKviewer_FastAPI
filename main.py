from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import simulator
import traceback

app = FastAPI()

# so /api/rooms/{room_name} endpoint calls predict_internal_temp:
@app.get("/api/simulate/{room_name}")
def get_room(room_name: str):
    try:
        temp = simulator.predict_internal_temp(room_name)
    except ValueError as e:
        traceback.print_exc()                  # ← prints full stack for 404s
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        traceback.print_exc()                  # ← prints full stack for any unexpected error
        raise HTTPException(
            status_code=500,
            detail=f"Simulator error: {e!r}"
        )
    return {"predicted_temp": temp}
# what happens to the content I return from this function - FastAPI serves up the same to any HTTP client—be it curl, Postman, or browser’s fetch—and it’s up to that client to decide how to display or consume it

# Mount the entire `static/` directory at the web root,
# with html=True so "/" serves index.html by default.
app.mount(
    "/",
    StaticFiles(directory="static", html=True),
    name="static"
)


