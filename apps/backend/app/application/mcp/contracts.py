"""Versioned, transport-neutral LensWord MCP contract registry.

An MCP adapter may expose these descriptors over stdio/HTTP, but it must map
calls to application use cases only—repositories never cross this boundary.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from app.domain.services.companion_activities import ActivityType
from app.domain.services.mcp_policy import AccessClass

CONTRACT_VERSION = "1.0.0"
MAX_PAGE_SIZE = 100

# Bounded, closed vocabulary of where a developer-context sighting came from
# (issue #188 TODOs 2/4). Kept here, beside the contract that names it in a
# tool schema, so the schema and the use case that enforces it again
# (app.application.use_cases.mcp_dev_workflow) can never quietly diverge.
# The first eight are developer-workflow surfaces and are intentional, not
# copied from a sibling product: issue #188's whole premise is a learner who
# meets vocabulary while working, so "I saw this word in a commit message"
# is the sighting it was built to record.
#
# They were, however, the *only* vocabulary available, which made the tool
# unusable for a learner who met a word in a subtitle or a conversation —
# every ordinary language-learning context had to be forced into
# "explanation" or dropped. The learner-facing kinds below are added rather
# than substituted: these strings are persisted on existing
# LearningObservation rows, so removing one would orphan the history that
# already references it.
CONTEXT_KINDS = (
    # Developer-workflow sightings (issue #188).
    "commit_message",
    "pull_request",
    "readme",
    "documentation",
    "terminal_output",
    "prompt",
    "explanation",
    "stack_trace",
    # Everyday language-learning sightings.
    "conversation",
    "reading",
    "subtitle",
    "song_lyrics",
    "chat_message",
    "video",
    "podcast",
)

@dataclass(frozen=True, slots=True)
class ToolContract:
    name: str
    schema_id: str
    access: AccessClass
    input_schema: dict
    errors: tuple[str, ...] = ("unauthorized", "validation_error", "not_found", "rate_limited")

    @property
    def title(self) -> str:
        """Human-readable display name (MCP `Tool.title`) — see TOOL_DOCS."""
        return TOOL_DOCS[self.name][0]

    @property
    def description(self) -> str:
        """What an LLM client reads when choosing this tool — see TOOL_DOCS."""
        return TOOL_DOCS[self.name][1]

    @property
    def annotations(self) -> dict:
        """MCP `Tool.annotations`: the behavioural hints a host uses to decide
        whether a call needs a human confirmation prompt.

        Every field is stated explicitly rather than left to the schema's
        defaults, because those defaults describe the most dangerous tool
        imaginable — `readOnlyHint` defaults to false, `destructiveHint` to
        true, `openWorldHint` to true. A tool that sends no annotations is
        therefore treated as an open-world, potentially destructive writer,
        which is why every tool here — pure reads included — used to prompt
        for confirmation before every call.

        These are hints, not enforcement: the real authorization boundary is
        MCPPolicyGate's per-tool grants (mcp.py) and the OAuth scopes that
        provision them, neither of which trusts anything a client sends. The
        spec is explicit that clients must treat annotations from untrusted
        servers as untrusted, so nothing here is load-bearing for security.
        """
        if self.access is AccessClass.READ:
            # `destructiveHint`/`idempotentHint` are defined as meaningful
            # only when `readOnlyHint` is false, so they are omitted rather
            # than set to a value that reads as significant but isn't.
            return {"title": self.title, "readOnlyHint": True, "openWorldHint": False}
        return {
            "title": self.title,
            "readOnlyHint": False,
            "destructiveHint": self.name in DESTRUCTIVE_TOOLS,
            # Every write contract mandates a client-chosen `request_id`
            # (see `_schema(write=True)`), which mcp.py's IdempotencyStore
            # dedupes on — so repeating an identical call genuinely has no
            # additional effect, which is exactly what this hint claims.
            "idempotentHint": True,
            "openWorldHint": False,
        }

def _schema(properties: dict, required: list[str] = [], *, write: bool = False) -> dict:
    base = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False, "properties": properties, "required": list(required)}
    if write:
        # Mandatory idempotency for writes (issue #196 TODO 4): every write
        # tool's caller must supply a client-chosen `request_id`, so
        # mcp.py's IdempotencyStore can always dedupe a retried call instead
        # of that being an opt-in the caller could simply omit.
        base["properties"]["request_id"] = {"type": "string", "minLength": 1, "maxLength": 128}
        base["required"].append("request_id")
    return base

# Writes that are not purely additive, i.e. that take something away or
# close a door the learner cannot reopen. `destructiveHint` is specified as
# "may perform destructive updates ... if false, the tool performs only
# additive updates", so this set is deliberately small: adding a word,
# recording an answer, or finishing an activity all only ever append to the
# learner's record, and marking them destructive would train users to click
# through the confirmations that actually matter.
DESTRUCTIVE_TOOLS = frozenset({
    # Stops work already in flight; committed partial results survive, but
    # the remaining work is abandoned.
    "lensword_cancel_companion_task",
    # Irreversible by design — a finished session cannot be resumed, so an
    # accidental call costs the learner their whole session context.
    "lensword_finish_companion_session",
    # Removes a word and, with it, the spaced-repetition history that word
    # accumulated. There is no archive tier in the domain today (see
    # DeleteWordUseCase), so this is a hard delete and the host should
    # always confirm it — the tool additionally refuses to act without an
    # explicit `confirmed: true`.
    "lensword_delete_word",
})

# Human-facing tool documentation: `name -> (title, description)`.
#
# Kept in one prose block rather than threaded through the dense contract
# table below, because these strings are the tool-selection interface an LLM
# client actually reads — they need to be reviewable side by side as writing,
# not buried per-line among JSON-schema fragments. Before this existed,
# apps/mcp/lensword_mcp/server.py sent every tool the placeholder
# `f"LensWord {name}"` as its description, which told a model nothing about
# what any tool did or when to reach for it.
#
# `name` is deliberately NOT made friendlier here: it is a stable API
# identifier that `MCPGrantModel.tool` rows and `mcp_scopes.SCOPE_TOOLS`
# both key on, so renaming one would silently invalidate every existing
# OAuth grant for it and break scope-to-tool mapping. MCP's `Tool.title`
# field exists for exactly this split — a stable machine name plus a
# separate human-readable label.
#
# Descriptions state what the tool does and when to use it, and name the
# constraint a caller most often gets wrong. They deliberately do not
# restate the input schema, which the client already receives in full.
TOOL_DOCS: dict[str, tuple[str, str]] = {
    "lensword_add_word": (
        "Add Vocabulary Word",
        "Add one vocabulary word to a specific group in the learner's collection, "
        "optionally with its translations. Use when the learner names a word they "
        "want to study. To add several words the learner has already chosen, use "
        "Add Vocabulary Words — one call, not one per word. For pulling many words "
        "out of a passage at once, use Extract Vocabulary from Text instead.",
    ),
    "lensword_add_words": (
        "Add Vocabulary Words",
        "Add up to 100 vocabulary words to one group in a single call, each "
        "optionally with its translations. Every word joins the same group and is "
        "recorded in that group's language, so use this for a list the learner has "
        "already decided on — Extract Vocabulary from Text is still the right tool "
        "for finding candidate words inside a passage. Words that cannot be added "
        "are returned in `skipped` with their position and a reason; the rest are "
        "still saved.",
    ),
    "lensword_search_words": (
        "Search Vocabulary",
        "Search the learner's saved vocabulary by term or translation and return "
        "matching words with their identifiers. Use this first when you need a "
        "word_id for another tool, or to check whether a word is already saved. "
        "Results are paginated with a cursor.",
    ),
    "lensword_extract_vocabulary": (
        "Extract Vocabulary from Text",
        "Analyse a passage of text and add the vocabulary worth studying from it "
        "to a group, skipping words the learner already knows. Use for articles, "
        "subtitles, or any material the learner is reading. Bounded to 20,000 "
        "characters per call; prefer Start Background Extraction Task for long "
        "material when the client supports tasks.",
    ),
    "lensword_get_due_reviews": (
        "List Due Reviews",
        "List the words whose spaced-repetition interval has elapsed and are due "
        "for review now, optionally limited to one group. Use to answer what the "
        "learner should study next. Reading this does not start a session or "
        "change any schedule.",
    ),
    "lensword_create_study_session": (
        "Create Study Session",
        "Open a new review session over the learner's due words and return its "
        "session_id plus the words it contains. Required before Record Review "
        "Answer, which needs that session_id.",
    ),
    "lensword_generate_exercises": (
        "Generate Practice Exercises",
        "Generate practice exercises for one saved word — translation recall, "
        "definition matching, or cloze (fill-in-the-blank). Use when the learner "
        "wants to drill a specific word rather than run a scheduled review. To "
        "drill several words, use Generate Practice Exercises For Words instead.",
    ),
    "lensword_generate_exercises_for_words": (
        "Generate Practice Exercises For Words",
        "Generate practice exercises of one kind — translation recall, definition "
        "matching, or cloze — for up to 100 saved words in a single call. Use when "
        "the learner wants to drill a set of words rather than run a scheduled "
        "review. Words that cannot be drilled are returned in `skipped` with a "
        "reason; the rest still produce exercises.",
    ),
    "lensword_get_learning_progress": (
        "Get Learning Progress",
        "Return the learner's aggregate progress: words learned, review accuracy, "
        "streaks, and study time, for a given week or the current one. Use for "
        "'how am I doing' questions and progress summaries.",
    ),
    "lensword_record_answer": (
        "Record Review Answer",
        "Record the outcome of one word in an open study session as correct, "
        "incorrect, or skipped, which advances that word's spaced-repetition "
        "schedule. Call once per word reviewed. This is the only tool that "
        "changes review scheduling, so do not call it for hypothetical or "
        "practice answers the learner did not actually give.",
    ),
    "lensword_start_extraction_task": (
        "Start Background Extraction Task",
        "Queue vocabulary extraction from a long passage as a durable background "
        "task and return its task_id immediately, instead of blocking until it "
        "finishes. Use for material too long to process in one call; poll with "
        "Get Background Task Status. Requires an open companion session.",
    ),
    "lensword_get_companion_task": (
        "Get Background Task Status",
        "Return a background task's current status, progress, and any partial or "
        "final result. Poll this after starting a task; partial results are "
        "marked as such and are safe to show while the task is still running.",
    ),
    "lensword_cancel_companion_task": (
        "Cancel Background Task",
        "Stop a running background task. Work already completed and committed is "
        "kept and remains visible as a partial result.",
    ),
    "lensword_start_companion_session": (
        "Start Companion Session",
        "Open a companion session, the durable container that learning activities "
        "and background tasks belong to, and return its session_id. Required "
        "before any activity or task tool. Resume an existing session rather than "
        "starting a second one for the same conversation.",
    ),
    "lensword_get_companion_session": (
        "Get Companion Session",
        "Return a companion session's current state, including its status and the "
        "activities and tasks it contains. Use to re-establish context before "
        "continuing existing work.",
    ),
    "lensword_resume_companion_session": (
        "Resume Companion Session",
        "Return a paused companion session to active so its activities and tasks "
        "can continue. Use when picking work back up rather than starting a new "
        "session, which would lose the existing context.",
    ),
    "lensword_pause_companion_session": (
        "Pause Companion Session",
        "Pause an active companion session, preserving all of its state for later. "
        "Use when the learner steps away mid-activity.",
    ),
    "lensword_finish_companion_session": (
        "Finish Companion Session",
        "Close a companion session for good and return its summary. Use only when "
        "the work is genuinely complete — a finished session cannot be resumed.",
    ),
    "lensword_get_language_profile": (
        "Get Language Profile",
        "Return the learner's languages, proficiency level, and study preferences. "
        "Use to tailor difficulty and language choice before generating content or "
        "recommending words.",
    ),
    "lensword_check_known_term": (
        "Check If Term Is Known",
        "Report whether a term is already in the learner's vocabulary and how well "
        "it is known. Use before suggesting or adding a word to avoid teaching "
        "something already mastered.",
    ),
    "lensword_explain_for_user": (
        "Explain Word for This Learner",
        "Return an explanation of one saved word adapted to this learner's level "
        "and history with it, rather than a generic dictionary definition. Use "
        "when the learner asks what a word means or why they keep missing it.",
    ),
    "lensword_suggest_stretch_vocabulary": (
        "Suggest Stretch Vocabulary",
        "Suggest words just beyond the learner's current level — hard enough to "
        "grow, not so hard they stall. Use to recommend what to learn next; these "
        "are suggestions only and are not added to any group until you add them.",
    ),
    "lensword_record_context_occurrence": (
        "Record Word Encounter in Context",
        "Record that the learner met one saved word in real use — in conversation, "
        "reading, or an exercise — and whether they handled it correctly. This is "
        "evidence that informs future scheduling, so record only genuine "
        "encounters. Requires explicit confirmation before it is persisted. When "
        "one passage contained several known words, use Record Word Encounters in "
        "Context instead.",
    ),
    "lensword_record_context_occurrences": (
        "Record Word Encounters in Context",
        "Record that the learner met up to 100 saved words in one and the same "
        "real-use context — a single conversation, passage, or exercise — and "
        "whether they handled them correctly. The context kind, the outcome and "
        "the confirmation describe that shared context and apply to every word, so "
        "use this only when they genuinely do; record a word handled differently "
        "with its own call. This is evidence that informs future scheduling, so "
        "record only genuine encounters. Words that cannot be recorded are "
        "returned in `skipped` with a reason; the rest still apply.",
    ),
    "lensword_begin_learning_activity": (
        "Begin Learning Activity",
        "Start one measurable learning activity inside a companion session, given "
        "its type and prompt, and return its activity_id. Every other activity "
        "tool needs that activity_id.",
    ),
    "lensword_submit_activity_response": (
        "Submit Activity Response",
        "Submit the learner's answer to an open activity for evaluation. Send what "
        "the learner actually produced, unedited.",
    ),
    "lensword_get_activity_result": (
        "Get Activity Result",
        "Return an activity's evaluated result, including correctness and any "
        "feedback produced for it. Use after submitting a response.",
    ),
    "lensword_finish_learning_activity": (
        "Finish Learning Activity",
        "Close an activity and commit its outcome to the learner's record. Call "
        "once the activity is genuinely done; its result then counts toward "
        "progress and scheduling.",
    ),
    "lensword_request_hint": (
        "Request Activity Hint",
        "Return a graduated hint for an in-progress activity without revealing the "
        "answer. Requesting a hint is recorded as part of the activity, so it "
        "affects the outcome — use when the learner asks for help, not "
        "speculatively.",
    ),
    "lensword_explain_evidence": (
        "Explain Activity Evidence",
        "Return the recorded evidence behind an activity's evaluation — what was "
        "assessed and why it was judged that way. Use to justify a result to the "
        "learner instead of inventing a rationale.",
    ),
    # --- Group management ------------------------------------------------
    # Every word-writing tool takes a `group_id` it cannot obtain, which
    # left a caller to guess integers or send the learner to the web app.
    # These two close that loop.
    "lensword_create_group": (
        "Create Vocabulary Group",
        "Create a new vocabulary group (a deck) for one target language and return "
        "its group_id. Use before adding words when the learner has no suitable "
        "group yet. Check List Vocabulary Groups first — a group with the same "
        "name is not rejected, so calling this twice creates two decks.",
    ),
    "lensword_list_groups": (
        "List Vocabulary Groups",
        "List the learner's vocabulary groups with their identifiers, target "
        "language, and word counts. Use this first whenever another tool needs a "
        "group_id, rather than guessing one.",
    ),
    "lensword_list_group_words": (
        "List Words In Group",
        "List every word saved in one group, without a search term. Use for 'show "
        "me my X deck' questions. Search Vocabulary is for finding a word by its "
        "text across all groups; this is for enumerating one group.",
    ),
    # --- Word lifecycle ---------------------------------------------------
    "lensword_update_word": (
        "Update Vocabulary Word",
        "Correct a saved word's translations, example sentence, or mnemonic, or "
        "move it to another group, keeping its review history intact. Use this "
        "rather than deleting and re-adding, which would reset the word's "
        "spaced-repetition schedule to new. To set the same level, part of "
        "speech, category, or tags across several words, use Update Vocabulary "
        "Words instead.",
    ),
    "lensword_update_words": (
        "Update Vocabulary Words",
        "Set the same CEFR level, part of speech, category, or tags on up to 100 "
        "saved words at once. Only fields you supply are changed; an omitted field "
        "is left alone rather than cleared. Term and translations deliberately "
        "cannot be set this way — they are what makes a card that card, and one "
        "value cannot be right for a hundred of them. Words that are not this "
        "account's are reported in `skipped`. Review history is untouched.",
    ),
    "lensword_delete_word": (
        "Delete Vocabulary Word",
        "Permanently remove a word and its review history. This cannot be undone "
        "and there is no archive to restore from, so use it only on an explicit "
        "request from the learner; requires confirmed=true. To fix a mistake in a "
        "word, use Update Vocabulary Word instead so its history survives.",
    ),
    # --- Memory palace (method of loci) ----------------------------------
    "lensword_list_rooms": (
        "List Memory Palace Rooms",
        "List the learner's memory-palace rooms with their identifiers and the "
        "group each one visualises. Use this to obtain a room_id before placing a "
        "word.",
    ),
    "lensword_create_room": (
        "Create Memory Palace Room",
        "Create a memory-palace room for one vocabulary group and return its "
        "room_id. A room is a spatial canvas the learner places that group's words "
        "onto, so the group must exist first.",
    ),
    "lensword_place_word_in_room": (
        "Place Word In Room",
        "Place one word at a position on its group's memory-palace room canvas, as "
        "a method-of-loci anchor. Coordinates are percentages of the canvas, 0 to "
        "100. The word must belong to the room's own group. Placing an "
        "already-placed word moves it rather than duplicating it. To place "
        "several words, use Place Words In Room instead — it is a single call "
        "and updates the room atomically.",
    ),
    "lensword_place_words_in_room": (
        "Place Words In Room",
        "Place up to 100 words on one memory-palace room canvas in a single call. "
        "Prefer this over repeating Place Word In Room: every placement is applied "
        "to one loaded room and saved once, so a set of anchors cannot be half "
        "written by two calls racing each other. Each placement gives a word_id and "
        "canvas percentages 0 to 100, and every word must belong to the room's own "
        "group. Words that cannot be placed are returned in `skipped` with a "
        "reason; the rest still apply.",
    ),
    # --- MnemoLab ---------------------------------------------------------
    "lensword_get_mnemonics": (
        "Get Word Mnemonics",
        "Return the mnemonics saved for one word, strongest-scoring first. Use to "
        "remind a learner of a memory hook they already have before inventing a "
        "new one.",
    ),
    "lensword_generate_mnemonic": (
        "Generate Word Mnemonic",
        "Generate a new memory hook for one saved word in a chosen style. Returns "
        "the suggestion without saving it unless persist=true. This answers 'how "
        "do I remember this'; Explain Word For Learner answers 'what does this "
        "mean'.",
    ),
    # --- Knowledge graph --------------------------------------------------
    "lensword_get_word_map": (
        "Get Word Relationship Map",
        "Return the map of relationships (synonym, antonym, topic, collocation, "
        "confused-with) around one word, out to a chosen number of hops. Use to "
        "ground statements about which of the learner's words relate to each "
        "other, instead of inferring connections that were never recorded.",
    ),
}

TOOL_CONTRACTS = tuple(ToolContract(name, f"https://lensword.app/mcp/{CONTRACT_VERSION}/{name}.schema.json", access, schema) for name, access, schema in (
    ("lensword_add_word", AccessClass.WRITE, _schema({"group_id": {"type":"integer", "minimum":1}, "term":{"type":"string","minLength":1,"maxLength":255}, "target_language":{"type":"string"}, "translations":{"type":"array","maxItems":20,"items":{"type":"string","maxLength":255}}}, ["group_id","term","target_language"], write=True)),
    # Bulk vocabulary write (issue #347 Bug 5). `group_id` and
    # `target_language` stay top-level: an import lands in one group, and a
    # group has one language, so repeating them per item would invite a batch
    # that disagreed with itself. That shape is also what lets the group's
    # ownership be checked once for the whole call.
    ("lensword_add_words", AccessClass.WRITE, _schema({
        "group_id": {"type":"integer","minimum":1},
        "target_language": {"type":"string"},
        "items": {
            "type":"array","minItems":1,"maxItems":MAX_PAGE_SIZE,
            "items": {
                "type":"object","additionalProperties":False,
                "properties": {
                    "term": {"type":"string","minLength":1,"maxLength":255},
                    "translations": {"type":"array","maxItems":20,"items":{"type":"string","maxLength":255}},
                },
                "required":["term"],
            },
        },
    }, ["group_id","target_language","items"], write=True)),
    # The backend has had `PATCH /api/v1/words/bulk` since #140 but never
    # exposed it here, so an agent editing forty cards had to issue forty
    # `update_word` calls to reach a capability that already existed.
    ("lensword_update_words", AccessClass.WRITE, _schema({
        "word_ids": {"type":"array","minItems":1,"maxItems":MAX_PAGE_SIZE,"items":{"type":"integer","minimum":1}},
        "cefr_level": {"type":"string","maxLength":8},
        "part_of_speech": {"type":"string","maxLength":64},
        "category": {"type":"string","maxLength":128},
        "tags": {"type":"array","maxItems":50,"items":{"type":"string","maxLength":64}},
    }, ["word_ids"], write=True)),
    ("lensword_search_words", AccessClass.READ, _schema({"query":{"type":"string","maxLength":255}, "limit":{"type":"integer","minimum":1,"maximum":100}, "cursor":{"type":"string","maxLength":256}})),
    ("lensword_extract_vocabulary", AccessClass.WRITE, _schema({"group_id":{"type":"integer","minimum":1}, "text":{"type":"string","minLength":1,"maxLength":20000}, "target_language":{"type":"string"}, "max_items":{"type":"integer","minimum":1,"maximum":50}}, ["group_id","text","target_language"], write=True)),
    ("lensword_get_due_reviews", AccessClass.READ, _schema({"group_id":{"type":"integer","minimum":1}, "limit":{"type":"integer","minimum":1,"maximum":100}, "cursor":{"type":"string","maxLength":256}})),
    ("lensword_create_study_session", AccessClass.WRITE, _schema({"group_id":{"type":"integer","minimum":1}, "limit":{"type":"integer","minimum":1,"maximum":100}}, write=True)),
    ("lensword_generate_exercises", AccessClass.WRITE, _schema({"word_id":{"type":"integer","minimum":1}, "kind":{"enum":["translation","definition","cloze"]}}, ["word_id"], write=True)),
    ("lensword_generate_exercises_for_words", AccessClass.WRITE, _schema({"word_ids":{"type":"array","minItems":1,"maxItems":MAX_PAGE_SIZE,"items":{"type":"integer","minimum":1}}, "kind":{"enum":["translation","definition","cloze"]}}, ["word_ids"], write=True)),
    ("lensword_get_learning_progress", AccessClass.READ, _schema({"week":{"type":"string","maxLength":32, "description":"ISO-8601 week, e.g. '2026-W32'. Omit for the current week."}})),
    ("lensword_record_answer", AccessClass.WRITE, _schema({"session_id":{"type":"integer","minimum":1}, "word_id":{"type":"integer","minimum":1}, "outcome":{"enum":["correct","incorrect","skipped"]}}, ["session_id","word_id","outcome"], write=True)),
    # Companion task tools (#197 TODO 2): genuinely long-running work only.
    # `start_extraction_task` wraps the existing companion_tasks.py state
    # machine and the background executor in
    # app.infrastructure.jobs.companion_task_dispatch — it never does the
    # work synchronously itself, only creates the durable task record. The
    # MCP transport (apps/mcp/lensword_mcp/server.py) gates exposing it on
    # the client having declared task capability during initialize.
    # `get_companion_task`/`cancel_companion_task` are generic and cover any
    # task type, including `plan_generation` tasks created through
    # `app.api.routers.companion_tasks`'s own generate-plan/confirm-plan
    # flow (#194 TODO 4) — there is deliberately no `start_plan_generation_
    # task` tool here, since that flow already exists and this would only
    # duplicate it (see companion_task_dispatch.py's module docstring).
    ("lensword_start_extraction_task", AccessClass.WRITE, _schema({"companion_session_id":{"type":"string","minLength":1,"maxLength":64}, "text":{"type":"string","minLength":1,"maxLength":8000}, "target_language":{"type":"string","minLength":1,"maxLength":64}, "max_terms":{"type":"integer","minimum":1,"maximum":50}}, ["companion_session_id","text","target_language"], write=True)),
    ("lensword_get_companion_task", AccessClass.READ, _schema({"companion_session_id":{"type":"string","minLength":1,"maxLength":64}, "task_id":{"type":"string","minLength":1,"maxLength":64}}, ["companion_session_id","task_id"])),
    ("lensword_cancel_companion_task", AccessClass.WRITE, _schema({"companion_session_id":{"type":"string","minLength":1,"maxLength":64}, "task_id":{"type":"string","minLength":1,"maxLength":64}}, ["companion_session_id","task_id"], write=True)),
    # Durable companion sessions (#193 TODO 1). `session_id` is the opaque
    # hex id `CompanionSession.id` — bounded to 64 chars to match
    # CompanionSessionModel.id (String(64)), same as every other resource
    # id in this registry.
    ("lensword_start_companion_session", AccessClass.WRITE, _schema({
        "connection_id": {"type":"string","minLength":1,"maxLength":128},
        "client_id": {"type":"string","minLength":1,"maxLength":128},
        "goal": {"type":"string","maxLength":500},
        "language": {"type":"string","maxLength":64},
        "group_id": {"type":"integer","minimum":1},
        "difficulty": {"type":"string","maxLength":32},
        "active_activity": {"type":"string","maxLength":128},
    }, ["connection_id","client_id"], write=True)),
    ("lensword_get_companion_session", AccessClass.READ, _schema({"session_id": {"type":"string","minLength":1,"maxLength":64}}, ["session_id"])),
    ("lensword_resume_companion_session", AccessClass.WRITE, _schema({"session_id": {"type":"string","minLength":1,"maxLength":64}}, ["session_id"], write=True)),
    ("lensword_pause_companion_session", AccessClass.WRITE, _schema({"session_id": {"type":"string","minLength":1,"maxLength":64}}, ["session_id"], write=True)),
    ("lensword_finish_companion_session", AccessClass.WRITE, _schema({"session_id": {"type":"string","minLength":1,"maxLength":64}}, ["session_id"], write=True)),
    # Learner-aware developer-workflow tools (issue #188 TODO 3). Every one
    # of these but the last is read-only by construction: none of them can
    # mark a word mastered or create a Diagnosis. record_context_occurrence
    # is the sole write, and it writes a single low-trust LearningObservation
    # (never a Word/ReviewState mutation) — see
    # app.application.use_cases.mcp_dev_workflow for why that boundary holds.
    ("lensword_get_language_profile", AccessClass.READ, _schema({})),
    ("lensword_check_known_term", AccessClass.READ, _schema({"term":{"type":"string","minLength":1,"maxLength":255}, "target_language":{"type":"string","maxLength":64}}, ["term"])),
    ("lensword_explain_for_user", AccessClass.READ, _schema({"word_id":{"type":"integer","minimum":1}}, ["word_id"])),
    ("lensword_suggest_stretch_vocabulary", AccessClass.READ, _schema({"group_id":{"type":"integer","minimum":1}, "limit":{"type":"integer","minimum":1,"maximum":50}})),
    ("lensword_record_context_occurrence", AccessClass.WRITE, _schema({"word_id":{"type":"integer","minimum":1}, "context_kind":{"enum":list(CONTEXT_KINDS)}, "outcome":{"enum":["correct","incorrect"]}, "confirmed":{"type":"boolean"}}, ["word_id","context_kind","outcome","confirmed"], write=True)),
    # One passage usually contains several known words, which is the very
    # situation the single-item tool above exists to record. `context_kind`,
    # `outcome` and `confirmed` describe the passage, not the word, so they
    # stay scalar and only `word_ids` becomes an array.
    ("lensword_record_context_occurrences", AccessClass.WRITE, _schema({"word_ids":{"type":"array","minItems":1,"maxItems":MAX_PAGE_SIZE,"items":{"type":"integer","minimum":1}}, "context_kind":{"enum":list(CONTEXT_KINDS)}, "outcome":{"enum":["correct","incorrect"]}, "confirmed":{"type":"boolean"}}, ["word_ids","context_kind","outcome","confirmed"], write=True)),
    # Measurable companion activities and companion action tools (issue
    # #194 TODO 1). `begin_learning_activity` fixes `expected_evaluation`
    # once, and nothing here — not even `submit_activity_response` — can
    # change it afterward (#194 TODO 5): the companion cannot submit an
    # expected answer after seeing the learner's response.
    ("lensword_begin_learning_activity", AccessClass.WRITE, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_type": {"enum": [item.value for item in ActivityType]},
        "prompt": {"type":"string","minLength":1,"maxLength":4000},
        "expected_evaluation": {"type":"object"},
    }, ["session_id","activity_type","prompt"], write=True)),
    ("lensword_submit_activity_response", AccessClass.WRITE, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
        "response": {"type":"string","minLength":1,"maxLength":10000},
    }, ["session_id","activity_id","response"], write=True)),
    ("lensword_get_activity_result", AccessClass.READ, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
    }, ["session_id","activity_id"])),
    ("lensword_finish_learning_activity", AccessClass.WRITE, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
    }, ["session_id","activity_id"], write=True)),
    # A write, not a read: it increments the activity's bounded hint
    # counter (MAX_HINTS_PER_ACTIVITY) and persists that.
    ("lensword_request_hint", AccessClass.WRITE, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
    }, ["session_id","activity_id"], write=True)),
    ("lensword_explain_evidence", AccessClass.READ, _schema({
        "session_id": {"type":"string","minLength":1,"maxLength":64},
        "activity_id": {"type":"string","minLength":1,"maxLength":64},
    }, ["session_id","activity_id"])),
    # Group management. Until these existed, `group_id` was an input every
    # word-writing tool demanded and no tool could supply — a caller had to
    # guess an integer or abandon the MCP surface for the web app. `limit`/
    # `cursor` mirror the pagination shape `search_words` established.
    ("lensword_create_group", AccessClass.WRITE, _schema({
        "name": {"type":"string","minLength":1,"maxLength":128},
        "target_language": {"type":"string","minLength":1,"maxLength":64},
    }, ["name","target_language"], write=True)),
    ("lensword_list_groups", AccessClass.READ, _schema({
        "limit": {"type":"integer","minimum":1,"maximum":100},
        "cursor": {"type":"string","maxLength":256},
    })),
    ("lensword_list_group_words", AccessClass.READ, _schema({
        "group_id": {"type":"integer","minimum":1},
        "limit": {"type":"integer","minimum":1,"maximum":100},
        "cursor": {"type":"string","maxLength":256},
        "sort_by": {"enum":["added_at","term","next_review_at"]},
    }, ["group_id"])),
    # Word lifecycle. `update_word` is a partial update on purpose: every
    # field left out keeps its stored value, so correcting a translation
    # cannot silently erase an example sentence. Supplying `group_id` moves
    # the word between groups without disturbing its review state.
    ("lensword_update_word", AccessClass.WRITE, _schema({
        "word_id": {"type":"integer","minimum":1},
        "translations": {"type":"array","maxItems":20,"items":{"type":"string","maxLength":255}},
        "example_sentence": {"type":"string","maxLength":1000},
        "mnemonic": {"type":"string","maxLength":1000},
        "category": {"type":"string","maxLength":128},
        "group_id": {"type":"integer","minimum":1},
    }, ["word_id"], write=True)),
    # `confirmed` is a required boolean rather than an optional flag, so the
    # payload cannot be shortened into an accidental deletion. There is no
    # `mode: archive` here because the domain has no archive tier to route
    # to — see this tool's entry in DESTRUCTIVE_TOOLS.
    ("lensword_delete_word", AccessClass.WRITE, _schema({
        "word_id": {"type":"integer","minimum":1},
        "confirmed": {"type":"boolean"},
    }, ["word_id","confirmed"], write=True)),
    # Memory palace. `list_rooms`/`create_room` exist for the same reason
    # the group tools do: `place_word_in_room` needs a `room_id` that would
    # otherwise be unobtainable. Coordinates are percentages of the canvas,
    # matching RoomPlacement's own units rather than pixels, so a placement
    # survives the canvas being displayed at any size.
    ("lensword_list_rooms", AccessClass.READ, _schema({
        "limit": {"type":"integer","minimum":1,"maximum":100},
        "cursor": {"type":"string","maxLength":256},
    })),
    ("lensword_create_room", AccessClass.WRITE, _schema({
        "group_id": {"type":"integer","minimum":1},
        "name": {"type":"string","minLength":1,"maxLength":128},
        "icon": {"type":"string","maxLength":64},
    }, ["group_id","name"], write=True)),
    ("lensword_place_word_in_room", AccessClass.WRITE, _schema({
        "room_id": {"type":"integer","minimum":1},
        "word_id": {"type":"integer","minimum":1},
        "x_percent": {"type":"number","minimum":0,"maximum":100},
        "y_percent": {"type":"number","minimum":0,"maximum":100},
    }, ["room_id","word_id","x_percent","y_percent"], write=True)),
    # Batched siblings (issue #348). The single-item tools above stay: they
    # are correct for a one-off call, and removing one would invalidate the
    # OAuth grants already keyed on its name. `room_id` stays a top-level
    # field on the batch because only the coordinates vary per item — which
    # is precisely what lets the handler resolve and ownership-check the
    # room once and rewrite the aggregate once, instead of N times.
    ("lensword_place_words_in_room", AccessClass.WRITE, _schema({
        "room_id": {"type":"integer","minimum":1},
        "placements": {
            "type":"array","minItems":1,"maxItems":MAX_PAGE_SIZE,
            "items": {
                "type":"object","additionalProperties":False,
                "properties": {
                    "word_id": {"type":"integer","minimum":1},
                    "x_percent": {"type":"number","minimum":0,"maximum":100},
                    "y_percent": {"type":"number","minimum":0,"maximum":100},
                },
                "required":["word_id","x_percent","y_percent"],
            },
        },
    }, ["room_id","placements"], write=True)),
    # MnemoLab. Reading mnemonics is the one place a `mnemonic` string is
    # the point of the call rather than an incidental leak, so these two are
    # the deliberate exception to the redaction rule bindings.py documents.
    ("lensword_get_mnemonics", AccessClass.READ, _schema({
        "word_id": {"type":"integer","minimum":1},
        "limit": {"type":"integer","minimum":1,"maximum":20},
    }, ["word_id"])),
    ("lensword_generate_mnemonic", AccessClass.WRITE, _schema({
        "word_id": {"type":"integer","minimum":1},
        "style": {"enum":["visual","phonetic","story","association"]},
        "persist": {"type":"boolean"},
    }, ["word_id"], write=True)),
    # Knowledge graph. `depth` is capped at 3 because the traversal is a
    # breadth-first walk over an in-memory graph of the learner's whole
    # vocabulary; beyond three hops the result stops being a useful "related
    # words" answer and starts being most of the collection.
    ("lensword_get_word_map", AccessClass.READ, _schema({
        "word_id": {"type":"integer","minimum":1},
        "depth": {"type":"integer","minimum":1,"maximum":3},
        "limit": {"type":"integer","minimum":1,"maximum":50},
    }, ["word_id"])),
))

def capabilities() -> dict:
    return {"version": CONTRACT_VERSION, "compatibility": "minor versions are additive; major versions require explicit client opt-in", "tools": [{"name": tool.name, "title": tool.title, "description": tool.description, "annotations": tool.annotations, "schema_id": tool.schema_id, "access": tool.access.value, "input_schema": tool.input_schema, "errors": tool.errors} for tool in TOOL_CONTRACTS]}


def validate_payload(contract: ToolContract, payload: dict) -> str | None:
    """Validate the bounded JSON-schema subset used by MCP contracts.

    Keeping this small validator beside the registry makes contract enforcement
    available without accepting arbitrary schema features or adding a second
    dynamic execution surface. It deliberately fails closed on every unknown
    property and malformed primitive.

    `request_id` is always allowed even when a READ contract's schema doesn't
    declare it: every apps/mcp client call (server.py's BackendClient.invoke)
    attaches one unconditionally, since a caller can't generally know a
    tool's access class up front. The /api/v1/mcp/invoke route handler
    (api/routers/mcp.py) already treats request_id as optional/unused for
    reads and mandatory for writes (its `contract.access != AccessClass.READ`
    checks) — this validator rejecting it outright for reads contradicted
    that route handler's own logic and broke every read-tool call made
    through apps/mcp's stdio server.
    """
    schema = contract.input_schema
    if not isinstance(payload, dict):
        return "payload must be an object"
    properties = schema["properties"]
    unknown = set(payload) - set(properties) - {"request_id"}
    if unknown:
        return f"unsupported payload field: {sorted(unknown)[0]}"
    missing = [name for name in schema.get("required", []) if name not in payload]
    if missing:
        return f"missing required payload field: {missing[0]}"
    for name, value in payload.items():
        if name == "request_id" and name not in properties:
            continue
        error = _check_value(name, value, properties[name])
        if error is not None:
            return error
    return None


def _check_value(name: str, value: Any, rules: dict) -> str | None:
    """Validate one value against one property's rules, recursively.

    Split out of `validate_payload` so array items are held to the same
    standard as top-level fields. Before the batch tools (issue #348) the
    only item type this validator understood was `string`; an array of
    integers or of objects therefore passed through entirely unvalidated,
    which is the same silent gap the `number` branch below was added to
    close. A schema the registry publishes but does not enforce is worse
    than no schema, because the handler behind it is written trusting it.
    """
    if "enum" in rules and value not in rules["enum"]:
        return f"invalid value for {name}"
    expected = rules.get("type")
    if expected == "string":
        if not isinstance(value, str): return f"{name} must be a string"
        if len(value) < rules.get("minLength", 0) or len(value) > rules.get("maxLength", float("inf")):
            return f"{name} has an invalid length"
    elif expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return f"{name} must be an integer"
    elif expected == "integer" and not rules.get("minimum", float("-inf")) <= value <= rules.get("maximum", float("inf")):
        return f"{name} is out of range"
    elif expected == "number":
        # Room placement coordinates are the first fractional inputs in
        # the registry. Without this branch a "number" property matched
        # no case at all and passed through entirely unvalidated, which
        # would have made this validator quietly weaker than the schema
        # it publishes. `bool` is excluded for the same reason as above:
        # it is an `int` subclass in Python and is never a coordinate.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{name} must be a number"
        if not rules.get("minimum", float("-inf")) <= value <= rules.get("maximum", float("inf")):
            return f"{name} is out of range"
    elif expected == "array":
        if not isinstance(value, list): return f"{name} must be an array"
        if len(value) < rules.get("minItems", 0): return f"{name} has too few items"
        if len(value) > rules.get("maxItems", float("inf")): return f"{name} has too many items"
        item_rules = rules.get("items", {})
        if item_rules:
            for index, item in enumerate(value):
                error = _check_value(f"{name}[{index}]", item, item_rules)
                if error is not None:
                    return error
    elif expected == "object" and "properties" in rules:
        # Only schemas that describe their shape are checked. A bare
        # `{"type": "object"}` — `begin_learning_activity`'s
        # `expected_evaluation` is one — stays deliberately free-form.
        if not isinstance(value, dict): return f"{name} must be an object"
        item_properties = rules["properties"]
        unknown = sorted(set(value) - set(item_properties))
        if unknown: return f"{name} has an unsupported field: {unknown[0]}"
        missing = [field for field in rules.get("required", []) if field not in value]
        if missing: return f"{name} is missing required field: {missing[0]}"
        for field, item_value in value.items():
            error = _check_value(f"{name}.{field}", item_value, item_properties[field])
            if error is not None:
                return error
    elif expected == "boolean" and not isinstance(value, bool):
        return f"{name} must be a boolean"
    return None
