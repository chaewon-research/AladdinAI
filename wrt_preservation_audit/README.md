# AladdinAI WRT document-preservation diagnostic

**Scope:** Independent investigation requested after Aladdin invited a WRT review. No upstream changes or PR. Synthetic, non-sensitive test documents only.

**Source snapshot reviewed:** `aliyevaladddin/AladdinAI` main at commit `7f2e87719d42fee7c28e5af8825b46c6c3bf9b78` (27 September 2026). If main advances, record the new commit before interpreting results.

## What is in this package

- `fixtures/`: seven deliberately small DOCX documents. One contains a **targeted edit**, with a paragraph, table and image that should remain unaffected. Every fixture was checked for structural validity and rendered to inspect its original appearance.
- `wrt_preservation_probe.py`: standard-library-only test runner. Uses the **actual native AladdinAI WRT CLI** to perform DOCX → WRT → DOCX, makes the one targeted text substitution where appropriate, checks text, tables, formatting, media bytes and image order, and writes a JSON report.
- `make_fixtures.py`: optional regeneration script (requires `python-docx` and Pillow).
- `.github/workflows/wrt-preservation-audit.yml`: optional Ubuntu GitHub Actions workflow. It does not run unless copied to a fork's `.github/workflows/` directory and triggered.

The test program prints checks as **PASS** or **FAIL** but intentionally exits zero when the diagnostic completes, so the complete report is retained. A failed check is not automatically a project defect; compare it with the explicitly supported WRT format before reporting.

## Static review observations (NOT results of running the native converter)

The current `backend/native/wrt/wrt_docx.c` implementation gives several precise hypotheses worth testing:

1. **Inline image position.** `docx_to_wrt` buffers images separately for each paragraph and appends `images_buf` before `para_buf`, regardless of where the drawing appeared among text runs. `wrt_to_docx` emits image tags as separate Word paragraphs. This may move an inline picture from its original position after a no-op conversion.
2. **Table cell formatting.** DOCX table parsing concatenates `<w:t>` text inside each cell without checking individual run-format properties. Bold text in a table cell may lose its emphasis after conversion.
3. **Pipes inside table cells.** The WRT table representation is pipe-delimited. The current reader and writer show no escaping for a literal `|` inside cell content. The test documents expose that limitation without asserting all special-character cases are supported.
4. **Embedded JPEG metadata.** The WRT → DOCX writer gives all imported images filenames like `image1.png`, although DOCX → WRT emits image MIME types based on actual source filenames. A JPEG may retain JPEG bytes while receiving a PNG name; test the exported package metadata instead of relying only on image counts.

Source: https://github.com/aliyevaladddin/AladdinAI/blob/7f2e87719d42fee7c28e5af8825b46c6c3bf9b78/backend/native/wrt/wrt_docx.c

The existing test suite has tests for basic DOCX image round trips and C markup/HTML conversion, but these particular *document-diff* cases warrant independent checks. The pipeline does not demonstrate that a live LLM agent executes a safe edit; the `targeted_edit` fixture uses a deterministic WRT text substitution as an initial software-level proxy.

## Run against the native engine

The native C Makefile expects Linux/Unix, GCC, `libzip` and `zlib`. On Ubuntu or WSL Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y gcc make libzip-dev zlib1g-dev
# In a clone of aliyevaladddin/AladdinAI at the reviewed commit:
make -C backend/native/wrt wrt-engine
# Provide an absolute path to this extracted package and to the binary:
python3 /path/to/wrt_preservation_audit/wrt_preservation_probe.py \
    --engine /path/to/AladdinAI/backend/native/wrt/wrt-engine \
    --out /path/to/wrt_preservation_results.json
```

Run the fixture integrity check on any operating system with Python 3.10+:

```bash
python wrt_preservation_probe.py --check-fixtures-only
```

**Alternative with no local C setup:** Copy this package's `wrt_preservation_audit/` folder to the root of your AladdinAI fork, and its `.github/workflows/wrt-preservation-audit.yml` to your fork's top-level `.github/workflows/`. Push the work to a branch named `audit/wrt-preservation` and enable Actions for the fork if needed. The workflow builds the native engine on Ubuntu and uploads `wrt-preservation-report` as an Actions artifact. Keep it in your fork while validating results; do not open an upstream PR or publicly attribute a defect until the report is reviewed and the behavior is confirmed to be inside agreed project scope.

**No external model/GPU needed. No Hugging Face job needed.**
