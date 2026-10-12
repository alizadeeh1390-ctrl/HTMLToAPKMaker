import os
import re
import shutil
import tempfile
import subprocess
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="HTML to APK Builder")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {
        "status": "ok",
        "message": "HTML to APK build service is running"
    }


@app.post("/build")
async def build_apk(
    html_file: UploadFile = File(...),
    app_name: str = Form("My HTML App"),
    package_id: str = Form("com.example.htmlapp"),
    logo_file: UploadFile = File(None),
):
    workdir = tempfile.mkdtemp(prefix="htmlapk_")

    try:
        safe_name = re.sub(r"[^A-Za-z0-9 ]", "", app_name).strip()
        if not safe_name:
            safe_name = "My HTML App"

        if not re.fullmatch(
            r"[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+",
            package_id
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid package ID. Example: com.example.myapp"
            )

        project = Path(workdir) / "project"
        www = project / "www"
        www.mkdir(parents=True, exist_ok=True)

        html_data = await html_file.read()
        if not html_data:
            raise HTTPException(
                status_code=400,
                detail="The HTML file is empty."
            )

        (www / "index.html").write_bytes(html_data)

        if logo_file and logo_file.filename:
            logo_data = await logo_file.read()
            extension = Path(logo_file.filename).suffix.lower()

            if extension not in [".png", ".jpg", ".jpeg", ".webp"]:
                raise HTTPException(
                    status_code=400,
                    detail="Logo must be PNG, JPG, JPEG or WEBP."
                )

            (www / ("logo" + extension)).write_bytes(logo_data)

        env = os.environ.copy()

        subprocess.run(
            [
                "cordova",
                "create",
                str(project),
                package_id,
                safe_name
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120
        )

        www.mkdir(parents=True, exist_ok=True)
        (www / "index.html").write_bytes(html_data)

        if logo_file and logo_file.filename:
            logo_data = await logo_file.read()
            extension = Path(logo_file.filename).suffix.lower()
            if extension in [".png", ".jpg", ".jpeg", ".webp"]:
                (www / ("logo" + extension)).write_bytes(logo_data)

        subprocess.run(
            ["cordova", "platform", "add", "android"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
            env=env
        )

        subprocess.run(
            ["cordova", "build", "android", "--debug"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
            timeout=1200,
            env=env
        )

        apk_candidates = list(
            project.glob(
                "platforms/android/app/build/outputs/apk/debug/*.apk"
            )
        )

        if not apk_candidates:
            raise HTTPException(
                status_code=500,
                detail="Build finished but APK was not found."
            )

        apk_path = apk_candidates[0]
        output_path = Path(workdir) / "MyHTMLApp.apk"
        shutil.copy2(apk_path, output_path)

        return FileResponse(
            path=str(output_path),
            filename="MyHTMLApp.apk",
            media_type="application/vnd.android.package-archive",
            background=None
        )

    except HTTPException:
        raise

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Build timed out. Please try again."
        )

    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or exc.stdout or str(exc))[-3000:]
        raise HTTPException(
            status_code=500,
            detail="Android build failed: " + error
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Build failed: " + str(exc)
)
