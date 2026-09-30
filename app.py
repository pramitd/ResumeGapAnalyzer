from __future__ import annotations

import hmac
import os
import re
import shutil
import sys
import uuid
from datetime import date
from pathlib import Path

import streamlit as st
import yaml

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

import jd_analyzer
import render_resume
from application_package import create_application_zip
from groq_client import GROQ_MODEL, get_api_key

st.set_page_config(page_title="Resume Gap Analyzer", layout="wide")

# ---------------------------------------------------------------------------
# Per-user ephemeral workspace. No candidate data is shipped with the app.
# ---------------------------------------------------------------------------
if "workspace_id" not in st.session_state:
    st.session_state.workspace_id = uuid.uuid4().hex

WORKSPACE = Path("/tmp") / "resume_gap_analyzer" / st.session_state.workspace_id
WORKSPACE.mkdir(parents=True, exist_ok=True)

APPLICATIONS_DIR = WORKSPACE / "Applications"
APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_DIR = WORKSPACE / "profile"
MASTER_CONTENT = PROFILE_DIR / "master_content.yaml"
MASTER_PROJECT_DETAILS = PROFILE_DIR / "master_project_details.yaml"
MASTER_STYLE = PROFILE_DIR / "master_style.yaml"
MASTER_TEMPLATE = PROFILE_DIR / "master_template.html"
SOURCE_RESUME = PROFILE_DIR / "original_resume"


def sanitize_name(name: str) -> str:
    clean = re.sub(r"\s+", "_", name.strip())
    clean = re.sub(r'[<>:"/\\|?*]', "", clean)
    return clean or "Application"


def profile_ready() -> bool:
    return all(
        p.exists()
        for p in (
            MASTER_CONTENT,
            MASTER_PROJECT_DETAILS,
            MASTER_STYLE,
            MASTER_TEMPLATE,
        )
    )


def list_applications() -> list[Path]:
    return sorted(
        [p for p in APPLICATIONS_DIR.iterdir() if p.is_dir()],
        reverse=True,
    )


def create_application(company: str, role: str = "") -> Path:
    folder_name = f"{date.today().isoformat()}_{sanitize_name(company)}"
    if role.strip():
        folder_name += f"_{sanitize_name(role)}"

    new_dir = APPLICATIONS_DIR / folder_name
    if new_dir.exists():
        new_dir = APPLICATIONS_DIR / f"{folder_name}_{uuid.uuid4().hex[:6]}"

    new_dir.mkdir(parents=True)

    # Keep the original uploaded resume as source material for this application.
    # The uploaded source may have a .pdf/.docx/.txt suffix, so locate it
    # after a Streamlit rerun rather than relying on a transient local variable.
    source_candidates = sorted(PROFILE_DIR.glob("original_resume.*"))
    if source_candidates:
        source_resume = source_candidates[0]
        shutil.copy2(source_resume, new_dir / source_resume.name)

    return new_dir


def ensure_local_content(app_dir: Path) -> Path:
    path = app_dir / "content.yaml"
    if not path.exists():
        shutil.copy2(MASTER_CONTENT, path)
    return path


def get_secret(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


def require_password() -> None:
    if st.session_state.get("authenticated"):
        return

    st.title("🔐 Resume Gap Analyzer")
    st.subheader("Private access")

    password = st.text_input("Password", type="password")

    if st.button("Unlock", type="primary"):
        expected = get_secret("APP_PASSWORD")
        if not expected:
            st.error("APP_PASSWORD is not configured by the application owner.")
        elif hmac.compare_digest(password, expected):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.caption("This application is shared privately with friends and family.")
    st.stop()


require_password()

# ---------------------------------------------------------------------------
# Profile setup
#
# The profile/project DOCX is OPTIONAL.
#
# No DOCX:
#     Resume -> ONE Groq request -> profile + project context
#
# With DOCX:
#     Resume + DOCX -> ONE Groq request -> profile + richer project context
# ---------------------------------------------------------------------------
if not profile_ready():
    st.title("📄 Resume Gap Analyzer")
    st.subheader("Create your resume profile")

    st.write(
        "Upload your resume. An optional Word document can provide additional "
        "project/profile details. The app generates the profile and project "
        "context automatically."
    )

    with st.form("profile_setup"):
        uploaded_resume = st.file_uploader(
            "1. Upload your resume",
            type=["pdf", "docx", "txt"],
            help="Used to create your master resume profile.",
        )

        st.markdown("### 2. Optional profile / project-details Word document")
        st.write(
            "Optional: upload a DOCX containing project history, project tables, "
            "responsibilities, technologies, results, clients, or other profile "
            "details. If you skip it, Groq extracts project context from the resume."
        )

        uploaded_project_docx = st.file_uploader(
            "Upload optional profile/project details (.docx)",
            type=["docx"],
            key="project_details_docx_upload",
            help=(
                "The document may contain normal paragraphs and tables. "
                "One table per project is supported."
            ),
        )

        st.markdown("### 3. Resume appearance")
        accent_color = st.color_picker("Accent color", "#1F4E79")
        font_family = st.selectbox(
            "Font",
            ["Arial", "Calibri", "Helvetica", "Georgia", "Verdana"],
        )
        page_size = st.selectbox("Page size", ["A4", "Letter"])
        compact = st.checkbox("Compact layout", value=False)

        st.markdown("### 4. AI")
        st.info("Groq — GPT-OSS 120B")
        st.caption("One structured Groq request creates both profile files.")

        submitted = st.form_submit_button(
            "✨ Create my resume profile",
            type="primary",
        )

    if submitted:
        if uploaded_resume is None:
            st.error("Please upload your resume first.")
        else:
            try:
                with st.spinner(
                    "Reading your resume and creating the profile... "
                    "This uses one Groq request."
                ):
                    resume_text = jd_analyzer.extract_text_from_upload(uploaded_resume)

                    if len(resume_text.strip()) < 100:
                        raise ValueError(
                            "Very little text could be extracted from the uploaded "
                            "resume. Try a text-based PDF/DOCX/TXT resume."
                        )

                    project_doc_text = None
                    if uploaded_project_docx is not None:
                        project_doc_text = jd_analyzer.extract_project_details_docx(
                            uploaded_project_docx
                        )

                    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

                    # Preserve the exact uploaded resume as immutable source material.
                    # The generated/edited CV PDF is rendered separately from content.yaml.
                    resume_suffix = Path(uploaded_resume.name).suffix.lower() or ".bin"
                    source_resume_path = PROFILE_DIR / f"original_resume{resume_suffix}"
                    for old_source in PROFILE_DIR.glob("original_resume.*"):
                        old_source.unlink(missing_ok=True)
                    source_resume_path.write_bytes(uploaded_resume.getvalue())
                    SOURCE_RESUME = source_resume_path

                    # ONE Groq call. The optional DOCX is included when supplied.
                    profile, projects = jd_analyzer.generate_profile_bundle(
                        resume_text,
                        project_text=project_doc_text,
                        model=GROQ_MODEL,
                    )

                    MASTER_CONTENT.write_text(
                        yaml.safe_dump(
                            profile,
                            sort_keys=False,
                            allow_unicode=True,
                        ),
                        encoding="utf-8",
                    )

                    MASTER_PROJECT_DETAILS.write_text(
                        yaml.safe_dump(
                            projects,
                            sort_keys=False,
                            allow_unicode=True,
                        ),
                        encoding="utf-8",
                    )

                    jd_analyzer.generate_style_and_template(
                        {
                            "accent_color": accent_color,
                            "font_family": font_family,
                            "page_size": page_size,
                            "compact": compact,
                        },
                        PROFILE_DIR,
                    )

                    st.session_state.llm_model = GROQ_MODEL
                    st.session_state.project_details_source = (
                        "Resume + optional Word document → Groq JSON output"
                        if project_doc_text
                        else "Resume → Groq JSON output"
                    )

                st.success(
                    "Profile created: master_content.yaml, "
                    "master_project_details.yaml, master_style.yaml and "
                    "master_template.html."
                )
                st.rerun()

            except Exception as e:
                st.error(f"Profile generation failed: {e}")

    st.info(
        "The application owner supplies the Groq API key through Streamlit "
        "Secrets. Never enter an API key into the resume form."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
st.title("📄 Resume Gap Analyzer")

with st.sidebar:
    st.header("AI Settings")
    st.success("Groq — GPT-OSS 120B")
    st.caption(GROQ_MODEL)

    if get_api_key():
        st.caption("Groq API key: configured")
    else:
        st.error("GROQ_API_KEY is not configured.")

    st.divider()
    st.header("Application")

    apps = list_applications()
    labels = [p.name for p in apps]

    remembered = st.session_state.get("selected_app_name")
    default = labels.index(remembered) + 1 if remembered in labels else 0

    choice = st.selectbox(
        "Select application",
        ["— New application —"] + labels,
        index=default,
    )

    if choice != "— New application —":
        app_dir = APPLICATIONS_DIR / choice
        st.session_state.selected_app_name = choice
    else:
        app_dir = None

    st.caption(
        "Your generated profile is kept in this session workspace and is not "
        "part of the public source repository."
    )


if app_dir is None:
    st.title("🚀 Create a new application to start")
    st.info(
        "No job application is selected yet. Create a new application below "
        "to start the Job Description → ATS analysis → resume workflow."
    )

    with st.form("create_application_main"):
        st.markdown("### Create new application")
        company = st.text_input("Company name")
        role = st.text_input("Role (optional)")
        create = st.form_submit_button("➕ Create application", type="primary")

    if create:
        if not company.strip():
            st.error("Company name is required.")
        else:
            new_app = create_application(company, role)
            st.session_state.selected_app_name = new_app.name
            st.success(f"Created {new_app.name}. You can now open the Job Description tab.")
            st.rerun()

    st.stop()

st.subheader(app_dir.name)

tab_jd, tab_report, tab_content, tab_render, tab_profile = st.tabs(
    [
        "1. Job Description",
        "2. Gap Report",
        "3. Edit Content",
        "4. Render PDF",
        "5. Profile Files",
    ]
)

# ---------------------------------------------------------------------------
# Job Description / analysis
# ---------------------------------------------------------------------------
with tab_jd:
    jd_txt_path = app_dir / "JD.txt"
    jd_pdf_path = app_dir / "JD.pdf"

    existing = (
        jd_txt_path
        if jd_txt_path.exists()
        else (jd_pdf_path if jd_pdf_path.exists() else None)
    )

    if existing:
        st.info(f"JD already saved: {existing.name}")

    mode = st.radio(
        "Provide JD via",
        ["Paste text", "Upload file"],
        horizontal=True,
    )

    if mode == "Paste text":
        text = st.text_area(
            "Job description",
            value=(
                jd_txt_path.read_text(encoding="utf-8")
                if jd_txt_path.exists()
                else ""
            ),
            height=280,
        )

        if st.button("Save JD"):
            jd_txt_path.write_text(text, encoding="utf-8")
            st.success("JD saved.")
    else:
        uploaded = st.file_uploader(
            "Upload JD",
            type=["txt", "pdf"],
            key=f"jd_{app_dir.name}",
        )

        if uploaded is not None:
            suffix = uploaded.name.rsplit(".", 1)[-1]
            dest = app_dir / f"JD.{suffix}"
            dest.write_bytes(uploaded.getvalue())
            st.success(f"Saved {dest.name}")

    st.divider()

    if st.button("🔍 Run Gap Analysis", type="primary"):
        jd_path = jd_txt_path if jd_txt_path.exists() else jd_pdf_path

        if not jd_path.exists():
            st.error("No JD saved yet.")
        else:
            with st.spinner("Analyzing the JD with Groq — GPT-OSS 120B..."):
                try:
                    jd_text = jd_analyzer.extract_jd_text(jd_path)
                    content = jd_analyzer.load_yaml(
                        ensure_local_content(app_dir)
                    )
                    project_details = jd_analyzer.load_yaml(
                        MASTER_PROJECT_DETAILS
                    )

                    analysis = jd_analyzer.call_llm(
                        jd_text,
                        content,
                        project_details,
                        model=GROQ_MODEL,
                    )

                    st.session_state[f"analysis_{app_dir}"] = analysis

                    jd_analyzer.write_gap_report(
                        analysis,
                        app_dir / "gap_report.md",
                    )
                    jd_analyzer.write_study_notes(
                        analysis,
                        app_dir / "study_notes.md",
                    )

                    st.success(
                        f"Done — deterministic ATS score {analysis['match_score']}/100."
                    )
                except Exception as e:
                    st.error(f"Analysis failed: {e}")


# ---------------------------------------------------------------------------
# Gap report
# ---------------------------------------------------------------------------
with tab_report:
    analysis = st.session_state.get(f"analysis_{app_dir}")

    if analysis is None:
        report = app_dir / "gap_report.md"
        if report.exists():
            st.markdown(report.read_text(encoding="utf-8"))
        else:
            st.info("Run Gap Analysis first.")
    else:
        st.metric("ATS Match Score", f"{analysis['match_score']}/100")
        st.caption(analysis["match_score_rationale"])

        st.markdown("### 📊 Deterministic ATS Score Breakdown")
        st.caption(
            "Groq evaluates evidence; Python calculates the final score. "
            "The model does not directly choose the /100 score."
        )

        score_labels = {
            "hard_requirements": "Hard requirements",
            "skills_technologies": "Skills / technologies",
            "experience_alignment": "Experience alignment",
            "responsibilities": "Responsibilities",
            "keywords": "Keywords",
            "education_credentials": "Education / credentials",
        }

        breakdown = analysis.get("score_breakdown", {})
        for dimension, details in breakdown.items():
            label = score_labels.get(dimension, dimension)
            col_a, col_b, col_c = st.columns([4, 1, 2])
            with col_a:
                st.write(f"**{label}**")
            with col_b:
                st.write(f"{details['weight']}%")
            with col_c:
                st.write(
                    f"{details['score']:.0f}/100 "
                    f"→ {details['weighted_score']:.1f}"
                )

        with st.expander("🔎 Requirement evidence used for scoring"):
            for item in analysis.get("requirements", []):
                status_icon = {
                    "met": "✅",
                    "partial": "🟡",
                    "not_met": "❌",
                    "not_applicable": "⚪",
                }.get(item["status"], "•")
                st.markdown(
                    f"{status_icon} **{item['requirement']}** — "
                    f"{item['status'].replace('_', ' ')}"
                )
                st.caption(
                    f"{item['dimension'].replace('_', ' ')} · "
                    f"{item['importance']} · {item['evidence']}"
                )

        st.markdown("**Missing keywords / requirements**")
        st.write(
            ", ".join(analysis["missing_keywords"])
            if analysis["missing_keywords"]
            else "None identified."
        )

        c1, c2 = st.columns(2)

        with c1:
            st.markdown("**✅ Strong bullets**")
            for b in analysis["strong_bullets"]:
                st.markdown(
                    f"- **[{b['experience_id']}]** {b['bullet']}"
                )
                st.caption(b["why_strong"])

        with c2:
            st.markdown("**⚠️ Weak bullets**")
            for b in analysis["weak_bullets"]:
                st.markdown(
                    f"- **[{b['experience_id']}]** {b['bullet']}"
                )
                st.caption(b["why_weak"])

        st.markdown("**💡 Suggested improvements**")
        for s in analysis["improvement_suggestions"]:
            with st.expander(
                f"[{s['experience_id']}] "
                f"{s['suggested_bullet'][:80]}..."
            ):
                if s.get("original_bullet"):
                    st.markdown(
                        f"*Original:* {s['original_bullet']}"
                    )
                st.markdown(
                    f"*Suggested:* {s['suggested_bullet']}"
                )
                st.caption(s["rationale"])

        st.markdown("**📍 Where to include JD keywords / requirements**")
        for s in analysis["keyword_placement_suggestions"]:
            with st.expander(
                f"{s['priority'].upper()} — "
                f"{s['keyword_or_requirement']}"
            ):
                st.markdown(
                    f"**Recommended location:** "
                    f"{s['recommended_location']}"
                )
                st.markdown(
                    f"**Existing context:** {s['existing_context']}"
                )
                st.markdown(
                    f"**Suggested sentence:** {s['suggested_sentence']}"
                )
                st.caption(
                    f"Source: {s['source']} · {s['why_here']}"
                )

        st.markdown("**📚 Study topics**")
        for t in analysis["study_topics"]:
            st.markdown(
                f"- **{t['topic']}** — {t['reason']}"
            )


# ---------------------------------------------------------------------------
# Edit content
# ---------------------------------------------------------------------------
with tab_content:
    content_path = ensure_local_content(app_dir)

    current_text = content_path.read_text(encoding="utf-8")

    edited_text = st.text_area(
        "content.yaml",
        value=current_text,
        height=500,
    )

    if st.button("💾 Save content.yaml", type="primary"):
        try:
            yaml.safe_load(edited_text)
            content_path.write_text(
                edited_text,
                encoding="utf-8",
            )
            st.success("Saved.")
        except yaml.YAMLError as e:
            st.error(f"Invalid YAML — not saved. Error: {e}")

    st.divider()

    if st.button("🔄 Rerun ATS Analysis", type="primary"):
        jd_txt_path = app_dir / "JD.txt"
        jd_pdf_path = app_dir / "JD.pdf"
        jd_path = jd_txt_path if jd_txt_path.exists() else jd_pdf_path

        if not jd_path.exists():
            st.error("No saved JD found. Add a Job Description in Tab 1 first.")
        else:
            try:
                # Validate and save the current editor contents first.
                yaml.safe_load(edited_text)
                content_path.write_text(
                    edited_text,
                    encoding="utf-8",
                )

                with st.spinner(
                    "Rerunning ATS analysis with Groq — GPT-OSS 120B..."
                ):
                    jd_text = jd_analyzer.extract_jd_text(jd_path)

                    content = jd_analyzer.load_yaml(
                        content_path
                    )

                    project_details = jd_analyzer.load_yaml(
                        MASTER_PROJECT_DETAILS
                    )

                    # Use the exact same Groq analysis path as Tab 1.
                    analysis = jd_analyzer.call_llm(
                        jd_text,
                        content,
                        project_details,
                        model=GROQ_MODEL,
                    )

                    st.session_state[f"analysis_{app_dir}"] = analysis

                    jd_analyzer.write_gap_report(
                        analysis,
                        app_dir / "gap_report.md",
                    )

                    jd_analyzer.write_study_notes(
                        analysis,
                        app_dir / "study_notes.md",
                    )

                    st.success(
                        f"ATS analysis updated — deterministic ATS score "
                        f"{analysis['match_score']}/100. "
                        f"Open the Gap Report tab to see the result."
                    )

            except yaml.YAMLError as e:
                st.error(
                    f"Invalid YAML — changes were not analyzed: {e}"
                )
            except Exception as e:
                st.error(
                    f"ATS analysis failed: {e}"
                )

# ---------------------------------------------------------------------------
# Render PDF
# ---------------------------------------------------------------------------
def safe_pdf_name(name: str, app_dir: Path) -> str:
    clean = Path(name).name.strip()
    if not clean:
        clean = f"Resume_{app_dir.name}.pdf"
    if not clean.lower().endswith(".pdf"):
        clean += ".pdf"
    return clean


def render_current_resume(app_dir: Path, out_path: Path) -> Path:
    """Always render the current content/style/template into out_path."""
    content_path = ensure_local_content(app_dir)
    content = render_resume.load_yaml(content_path)
    style = render_resume.load_yaml(MASTER_STYLE)
    render_resume.render_pdf(
        content,
        style,
        MASTER_TEMPLATE,
        out_path,
    )
    return out_path


def pdf_needs_refresh(pdf_path: Path, app_dir: Path) -> bool:
    if not pdf_path.exists():
        return True
    sources = [
        ensure_local_content(app_dir),
        MASTER_STYLE,
        MASTER_TEMPLATE,
    ]
    pdf_mtime = pdf_path.stat().st_mtime_ns
    return any(path.exists() and path.stat().st_mtime_ns > pdf_mtime for path in sources)


with tab_render:
    content_path = ensure_local_content(app_dir)

    out_name = st.text_input(
        "Output filename",
        value=f"Resume_{app_dir.name}.pdf",
    )
    out_name = safe_pdf_name(out_name, app_dir)

    if st.button("🖨️ Render PDF", type="primary"):
        try:
            with st.spinner("Rendering the current edited resume PDF..."):
                out_path = app_dir / out_name
                render_current_resume(app_dir, out_path)
                st.session_state[f"last_pdf_{app_dir}"] = str(out_path)
                st.session_state[f"last_pdf_mtime_{app_dir}"] = out_path.stat().st_mtime_ns
            st.success(
                "PDF updated from the current content.yaml. "
                "The original uploaded resume remains unchanged as source material."
            )
        except Exception as e:
            st.error(f"PDF rendering failed: {e}")

    last_pdf = st.session_state.get(f"last_pdf_{app_dir}")
    if last_pdf:
        last_pdf_path = Path(last_pdf)
    else:
        last_pdf_path = app_dir / out_name

    if last_pdf_path.exists():
        # Always make the downloadable PDF current before exposing either
        # download button. This prevents stale PDFs in both downloads after
        # content.yaml/style/template edits.
        try:
            if pdf_needs_refresh(last_pdf_path, app_dir):
                with st.spinner("Updating the CV PDF from the latest edits..."):
                    render_current_resume(app_dir, last_pdf_path)
                    st.session_state[f"last_pdf_mtime_{app_dir}"] = last_pdf_path.stat().st_mtime_ns
        except Exception as e:
            st.error(f"Could not refresh the current CV PDF: {e}")
            st.stop()

        pdf_bytes = last_pdf_path.read_bytes()

        st.download_button(
            "⬇️ Download PDF",
            data=pdf_bytes,
            file_name=last_pdf_path.name,
            mime="application/pdf",
        )

        st.divider()
        st.subheader("📦 Complete Job Application")

        # Build the ZIP only after the current CV has been refreshed.
        try:
            application_zip = create_application_zip(app_dir)

            st.download_button(
                "📦 Download Complete Job Application",
                data=application_zip,
                file_name=f"{app_dir.name}.zip",
                mime="application/zip",
                type="primary",
                help=(
                    "Downloads the complete current application, including "
                    "the latest rendered CV, original uploaded resume, JD, "
                    "gap analysis, study notes and edited content.yaml."
                ),
            )
            st.caption(
                "The ZIP always contains the latest rendered CV. "
                "The original uploaded resume is kept separately as source material."
            )
        except Exception as e:
            st.error(f"Could not create application package: {e}")

        try:
            import fitz

            doc = fitz.open(last_pdf_path)
            pix = doc[0].get_pixmap(dpi=110)
            st.caption(f"{len(doc)} page(s) — current rendered CV")
            st.image(pix.tobytes("png"), width=650)
        except Exception:
            pass
    else:
        st.info(
            "No rendered CV yet. Edit your content if needed, then click "
            "**🖨️ Render PDF** to create the current resume PDF."
        )


# ---------------------------------------------------------------------------
# Generated profile files
# ---------------------------------------------------------------------------
with tab_profile:
    st.success(
        "Profile generated from the resume you uploaded. "
        "No fixed candidate data is bundled with this application."
    )

    source = st.session_state.get(
        "project_details_source",
        "Generated in this session.",
    )
    st.caption(f"Profile source: {source}")

    st.markdown("### Profile files")

    files = [
        MASTER_CONTENT,
        MASTER_PROJECT_DETAILS,
        MASTER_STYLE,
        MASTER_TEMPLATE,
    ]

    cols = st.columns(4)

    for col, path in zip(cols, files):
        with col:
            st.markdown(f"**{path.name}**")

            if path.exists():
                mime = (
                    "text/html"
                    if path.suffix == ".html"
                    else "text/plain"
                )

                st.download_button(
                    "Download",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=mime,
                    key=f"download_{path.name}",
                )

    st.divider()

    st.markdown("### Update project details from Word")
    st.caption(
        "Optional: upload another Word document to rebuild only "
        "master_project_details.yaml."
    )

    replacement = st.file_uploader(
        "Upload replacement project/profile details Word file",
        type=["docx"],
        key="replacement_project_docx",
    )

    if st.button("Generate project YAML from Word"):
        if replacement is None:
            st.error("Select a Word file first.")
        else:
            try:
                project_text = jd_analyzer.extract_project_details_docx(
                    replacement
                )

                with st.spinner(
                    "Reading project tables and generating YAML..."
                ):
                    data = jd_analyzer.generate_project_details_from_docx(
                        project_text,
                        model=GROQ_MODEL,
                    )

                MASTER_PROJECT_DETAILS.write_text(
                    yaml.safe_dump(
                        data,
                        sort_keys=False,
                        allow_unicode=True,
                    ),
                    encoding="utf-8",
                )

                st.session_state.project_details_source = (
                    "Replacement Word document → Groq"
                )

                st.success(
                    "master_project_details.yaml regenerated successfully."
                )
            except Exception as e:
                st.error(
                    f"Could not generate project details: {e}"
                )

    if st.checkbox("Show master_content.yaml"):
        st.code(
            MASTER_CONTENT.read_text(encoding="utf-8"),
            language="yaml",
        )

    if st.checkbox("Show master_project_details.yaml"):
        st.code(
            MASTER_PROJECT_DETAILS.read_text(encoding="utf-8"),
            language="yaml",
        )

    if st.checkbox("Show master_style.yaml"):
        st.code(
            MASTER_STYLE.read_text(encoding="utf-8"),
            language="yaml",
        )

    if st.checkbox("Show master_template.html"):
        st.code(
            MASTER_TEMPLATE.read_text(encoding="utf-8"),
            language="html",
        )

