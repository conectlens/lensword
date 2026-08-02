import csv
import io
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import CurrentUser, GroupRepo, OptionalAIProvider, WordRepo, rate_limit_import_upload, rate_limit_import_url
from app.api.schemas.imports import ImportCommitRequest, ImportParseResponse, ImportPreviewRecord, ImportPreviewRequest, ImportPreviewResponse, ImportRecordRequest, ImportUrlRequest
from app.application.use_cases.vocabulary import AddWordUseCase, WordInput, _require_group_owner
from app.domain.exceptions import AIProviderUnavailableError, EntityNotFoundError, PermissionDeniedError
from app.domain.services.documents import DocumentStructureError, DocumentTooLargeError
from app.domain.services.url_safety import UrlRejected
from app.infrastructure.document_parsers import detect_media_type, parse_document
from app.infrastructure.url_fetch import UrlFetchFailed, fetch_document

router = APIRouter(prefix='/api/v1/imports', tags=['vocabulary import'])


def _language(value: str | None, term: str) -> str:
    if value: return value
    return 'Turkish' if any(char in term.lower() for char in 'çğıöşü') else 'Unknown'


# Formats whose records come from columns rather than from prose. Everything
# else goes through the document parser registry, which returns sentences.
_RECORD_TYPES = {'text/csv', 'text/tab-separated-values', 'application/json'}


@router.post('/parse-url', response_model=ImportParseResponse, dependencies=[Depends(rate_limit_import_url)])
def parse_url(_user: CurrentUser, payload: ImportUrlRequest) -> ImportParseResponse:
    """Fetch a page the user pasted and parse it like an uploaded file.

    The fetch is the security-sensitive part, and its rules live in
    `url_safety` / `url_fetch`: only http(s) on standard ports, no embedded
    credentials, every resolved address checked against private space, and
    every redirect hop re-validated. Refusals are deliberately vague — saying
    which internal host was unreachable would turn this endpoint into a
    network scanner.
    """
    try:
        data, filename = fetch_document(payload.url)
    except UrlRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    except UrlFetchFailed as exc:
        # 502: the request was acceptable, the upstream page was not.
        raise HTTPException(502, str(exc)) from exc

    try:
        document = parse_document(data, filename)
    except DocumentTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except DocumentStructureError as exc:
        raise HTTPException(422, str(exc)) from exc

    records = [
        ImportRecordRequest(term=sentence.text[:200], translations=[])
        for section in document.sections for sentence in section.sentences
    ]
    if not records:
        raise HTTPException(422, 'No readable text found at that URL')
    return ImportParseResponse(records=records)


@router.post('/parse', response_model=ImportParseResponse, dependencies=[Depends(rate_limit_import_upload)])
async def parse_file(_user: CurrentUser, file: UploadFile = File(...)) -> ImportParseResponse:
    if not file.filename: raise HTTPException(422, 'A named import file is required')
    data = await file.read()
    try:
        media_type = detect_media_type(data, file.filename)
    except DocumentStructureError as exc: raise HTTPException(422, str(exc)) from exc

    # Prose formats (PDF, EPUB, DOCX, HTML, subtitles, Markdown, text) are
    # parsed into sections and sentences, and each sentence becomes a candidate
    # carrying where it came from. Bounds and refusals live in the parsers.
    if media_type not in _RECORD_TYPES:
        try:
            document = parse_document(data, file.filename)
        except DocumentTooLargeError as exc: raise HTTPException(413, str(exc)) from exc
        except DocumentStructureError as exc: raise HTTPException(422, str(exc)) from exc
        records = [
            ImportRecordRequest(term=sentence.text[:200], translations=[])
            for section in document.sections for sentence in section.sentences
        ]
        if not records: raise HTTPException(422, 'No readable text found in file')
        return ImportParseResponse(records=records)

    raw = data.decode('utf-8-sig', errors='replace')
    suffix = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'txt'
    try:
        if suffix == 'json': rows = json.loads(raw)
        elif suffix in {'csv', 'tsv'}:
            rows = list(csv.DictReader(io.StringIO(raw), delimiter='\t' if suffix == 'tsv' else ','))
        else: rows = [{'term': line.strip()} for line in raw.splitlines() if line.strip()]
    except (csv.Error, json.JSONDecodeError) as exc: raise HTTPException(422, f'Cannot parse import file: {exc}') from exc
    if not isinstance(rows, list): raise HTTPException(422, 'JSON import must be an array of records')
    records = []
    for row in rows:
        if not isinstance(row, dict): continue
        translations = row.get('translations', row.get('translation', []))
        if isinstance(translations, str): translations = [value.strip() for value in translations.split('|') if value.strip()]
        try: records.append(ImportRecordRequest(term=str(row.get('term', row.get('word', ''))).strip(), translations=translations if isinstance(translations, list) else [], definition=row.get('definition'), part_of_speech=row.get('part_of_speech'), cefr_level=row.get('cefr_level'), pronunciation=row.get('pronunciation')))
        except ValueError: continue
    if not records: raise HTTPException(422, 'No vocabulary records found in file')
    return ImportParseResponse(records=records)


@router.post('/preview', response_model=ImportPreviewResponse)
async def preview(payload: ImportPreviewRequest, current_user: CurrentUser, group_repo: GroupRepo, provider: OptionalAIProvider) -> ImportPreviewResponse:
    try: group = _require_group_owner(group_repo, payload.group_id, current_user.id)
    except EntityNotFoundError as exc: raise HTTPException(404, str(exc)) from exc
    except PermissionDeniedError as exc: raise HTTPException(403, str(exc)) from exc
    seen: set[str] = set(); records: list[ImportPreviewRecord] = []
    for record in payload.records:
        key = record.term.strip().casefold()
        if key in seen:
            records.append(ImportPreviewRecord(**record.model_dump(), source_language=_language(payload.source_language, record.term), status='duplicate', duplicate_of=record.term))
            continue
        seen.add(key); values = record.model_dump(); cleaned = False; metadata = {}
        missing = not values['translations'] or not values['definition'] or not values['part_of_speech'] or not values['cefr_level'] or not values['pronunciation']
        if payload.enrich_with_ai and missing and provider is not None:
            try:
                enriched = await provider.enrich_word(record.term, payload.source_language, group.target_language.value)
                values['translations'] = values['translations'] or enriched.translations
                values['definition'] = values['definition'] or (enriched.definitions[0] if enriched.definitions else None)
                values['part_of_speech'] = values['part_of_speech'] or enriched.part_of_speech
                values['cefr_level'] = values['cefr_level'] or enriched.cefr_level
                values['pronunciation'] = values['pronunciation'] or enriched.pronunciation
                metadata = {'provider': enriched.provider, 'model': enriched.model}; cleaned = True
            except AIProviderUnavailableError: pass
        records.append(ImportPreviewRecord(**values, source_language=_language(payload.source_language, record.term), status='ai_cleaned' if cleaned else 'ready', **metadata))
    return ImportPreviewResponse(records=records)


@router.post('/commit', status_code=status.HTTP_201_CREATED)
def commit(payload: ImportCommitRequest, current_user: CurrentUser, group_repo: GroupRepo, word_repo: WordRepo) -> dict[str, int]:
    added = 0
    for record in payload.records:
        if record.status == 'duplicate': continue
        AddWordUseCase(word_repo, group_repo).execute(current_user.id, payload.group_id, WordInput(term=record.term, target_language=_require_group_owner(group_repo, payload.group_id, current_user.id).target_language, translations=record.translations, definition=record.definition, part_of_speech=record.part_of_speech, cefr_level=record.cefr_level, pronunciation=record.pronunciation, ai_provider=record.provider, ai_model=record.model))
        added += 1
    return {'added': added}
