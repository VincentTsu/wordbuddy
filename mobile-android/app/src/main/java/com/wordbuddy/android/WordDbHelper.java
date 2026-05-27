package com.wordbuddy.android;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

final class WordDbHelper extends SQLiteOpenHelper {
    WordDbHelper(Context context) {
        super(context, Constants.DB_NAME, null, 1);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        createTables(db);
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        migrate(db);
    }

    @Override
    public void onOpen(SQLiteDatabase db) {
        super.onOpen(db);
        db.execSQL("PRAGMA foreign_keys=ON");
        createTables(db);
        migrate(db);
    }

    File dbFile(Context context) {
        return context.getDatabasePath(Constants.DB_NAME);
    }

    void checkpoint() {
        getWritableDatabase().rawQuery("PRAGMA wal_checkpoint(TRUNCATE)", null).close();
    }

    // ────────── Queries (all filter out soft-deleted rows) ──────────

    List<Word> dueWords() {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE deleted_at = '''' AND is_mastered = 0 AND next_review_date != '''' "
                        + "AND next_review_date <= ? ORDER BY RANDOM()",
                new String[]{Utils.today()})) {
            return readWords(c);
        }
    }

    List<Word> randomLearningWords(int count) {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE deleted_at = '''' AND is_mastered = 0 ORDER BY RANDOM() LIMIT ?",
                new String[]{String.valueOf(count)})) {
            return readWords(c);
        }
    }

    List<Word> allWords(String search) {
        SQLiteDatabase db = getReadableDatabase();
        String s = search == null ? "" : search.trim();
        if (s.isEmpty()) {
            try (Cursor c = db.rawQuery(
                    "SELECT * FROM words WHERE deleted_at = '''' ORDER BY created_at DESC LIMIT 200", null)) {
                return readWords(c);
            }
        }
        String like = "%" + s + "%";
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE deleted_at = '''' AND (word LIKE ? OR definition LIKE ?) "
                        + "ORDER BY created_at DESC LIMIT 200",
                new String[]{like, like})) {
            return readWords(c);
        }
    }

    int count(String where, String[] args) {
        SQLiteDatabase db = getReadableDatabase();
        StringBuilder fullWhere = new StringBuilder("deleted_at = ''");
        if (where != null) {
            String stripped = where.trim();
            // Strip leading WHERE if present (callers pass "WHERE ...")
            String upper = stripped.toUpperCase(java.util.Locale.US);
            if (upper.startsWith("WHERE ")) {
                stripped = stripped.substring(6).trim();
            }
            if (!stripped.isEmpty()) {
                fullWhere.append(" AND ").append(stripped);
            }
        }
        try (Cursor c = db.rawQuery("SELECT COUNT(*) FROM words WHERE " + fullWhere.toString(), args)) {
            return c.moveToFirst() ? c.getInt(0) : 0;
        }
    }

    Word getById(int id) {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE id = ? AND deleted_at = ''''",
                new String[]{String.valueOf(id)})) {
            List<Word> words = readWords(c);
            return words.isEmpty() ? null : words.get(0);
        }
    }

    Word getByText(String word) {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE word = ? COLLATE NOCASE AND deleted_at = ''''",
                new String[]{word})) {
            List<Word> words = readWords(c);
            return words.isEmpty() ? null : words.get(0);
        }
    }

    // ────────── Write operations ──────────

    void addOrUpdateFromJson(JSONObject data) throws Exception {
        String wordText = data.optString("word").trim();
        if (wordText.isEmpty()) {
            throw new IllegalArgumentException("单词不能为空");
        }
        SQLiteDatabase db = getWritableDatabase();
        String now = Utils.nowIso();

        ContentValues values = new ContentValues();
        values.put("word", wordText);
        values.put("phonetic", data.optString("phonetic"));
        values.put("part_of_speech", data.optString("part_of_speech"));
        values.put("definition", data.optString("definition"));
        values.put("english_definition", data.optString("english_definition"));
        values.put("examples_json", data.optJSONArray("examples") == null ? "[]" : data.getJSONArray("examples").toString());
        values.put("synonyms_json", data.optJSONArray("synonyms") == null ? "[]" : data.getJSONArray("synonyms").toString());
        values.put("notes", data.optString("notes"));
        values.put("updated_at", now);
        values.put("deleted_at", ""); // un-delete if re-added

        try (Cursor c = db.rawQuery("SELECT id FROM words WHERE word = ? COLLATE NOCASE", new String[]{wordText})) {
            if (c.moveToFirst()) {
                db.update("words", values, "word = ? COLLATE NOCASE", new String[]{wordText});
                return;
            }
        }

        values.put("review_stage", 0);
        values.put("next_review_date", Utils.dateAfterDays(Constants.REVIEW_INTERVALS[0]));
        values.put("created_at", now);
        db.insertOrThrow("words", null, values);
    }

    void addManualWord(String text) throws Exception {
        JSONObject obj = new JSONObject();
        obj.put("word", text);
        obj.put("definition", "");
        obj.put("examples", new JSONArray());
        obj.put("synonyms", new JSONArray());
        addOrUpdateFromJson(obj);
    }

    void markReviewed(int id, String result) {
        Word w = getById(id);
        if (w == null) return;

        int total = w.totalReviews + 1;
        int correct = w.correctReviews + (result.equals("known") ? 1 : 0);
        int newStage;

        if (result.equals("known")) {
            newStage = w.reviewStage + 1;
        } else if (result.equals("forgot")) {
            newStage = Math.max(w.reviewStage - 1, 0);
        } else {
            newStage = w.reviewStage;
        }

        boolean mastered = newStage >= Constants.REVIEW_INTERVALS.length;
        String nextReview;
        if (mastered) {
            nextReview = "";
        } else if (result.equals("fuzzy")) {
            nextReview = Utils.dateAfterDays(1);
        } else {
            nextReview = Utils.dateAfterDays(Constants.REVIEW_INTERVALS[newStage]);
        }

        String now = Utils.nowIso();
        ContentValues values = new ContentValues();
        values.put("review_stage", newStage);
        values.put("next_review_date", nextReview);
        values.put("is_mastered", mastered ? 1 : 0);
        values.put("total_reviews", total);
        values.put("correct_reviews", correct);
        values.put("last_reviewed_at", now);
        values.put("updated_at", now);

        getWritableDatabase().update("words", values, "id = ?", new String[]{String.valueOf(id)});
    }

    void deleteWord(int id) {
        String now = Utils.nowIso();
        ContentValues values = new ContentValues();
        values.put("deleted_at", now);
        values.put("updated_at", now);
        getWritableDatabase().update("words", values, "id = ?", new String[]{String.valueOf(id)});
    }

    // ────────── Merge ──────────

    /** Merge remote DB into local. For each word, the side with the newer updated_at wins. */
    int mergeFrom(File otherDbFile) {
        SQLiteDatabase remote = SQLiteDatabase.openDatabase(
                otherDbFile.getAbsolutePath(),
                null,
                SQLiteDatabase.OPEN_READONLY
        );
        int changed = 0;
        try (Cursor c = remote.rawQuery("SELECT * FROM words", null)) {
            for (Word remoteWord : readWords(c)) {
                Word localWord = getByTextIncludingDeleted(remoteWord.word);
                if (localWord == null) {
                    // New word from remote – insert
                    getWritableDatabase().insertOrThrow("words", null, valuesFor(remoteWord));
                    changed++;
                } else {
                    // Both have it – compare updated_at, later wins
                    int cmp = remoteWord.updatedAt.compareTo(localWord.updatedAt);
                    if (cmp > 0) {
                        // Remote is newer – overwrite local
                        getWritableDatabase().update(
                                "words",
                                valuesFor(remoteWord),
                                "word = ? COLLATE NOCASE",
                                new String[]{remoteWord.word}
                        );
                        changed++;
                    }
                    // else: local is newer or equal – keep local, do nothing
                }
            }
        } finally {
            remote.close();
        }
        return changed;
    }

    /**
     * Like getByText but also returns soft-deleted rows (needed for merge,
     * otherwise a remotely-deleted word would be re-inserted).
     */
    private Word getByTextIncludingDeleted(String word) {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE word = ? COLLATE NOCASE",
                new String[]{word})) {
            List<Word> words = readWords(c);
            return words.isEmpty() ? null : words.get(0);
        }
    }

    // ────────── Schema ──────────

    private void createTables(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS words ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                + "word TEXT NOT NULL UNIQUE COLLATE NOCASE,"
                + "phonetic TEXT DEFAULT '',"
                + "part_of_speech TEXT DEFAULT '',"
                + "definition TEXT DEFAULT '',"
                + "english_definition TEXT DEFAULT '',"
                + "examples_json TEXT DEFAULT '[]',"
                + "synonyms_json TEXT DEFAULT '[]',"
                + "notes TEXT DEFAULT '',"
                + "review_stage INTEGER DEFAULT 0,"
                + "next_review_date TEXT DEFAULT '',"
                + "total_reviews INTEGER DEFAULT 0,"
                + "correct_reviews INTEGER DEFAULT 0,"
                + "created_at TEXT NOT NULL,"
                + "last_reviewed_at TEXT DEFAULT '',"
                + "is_mastered INTEGER DEFAULT 0,"
                + "updated_at TEXT DEFAULT '',"
                + "deleted_at TEXT DEFAULT ''"
                + ")");
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_next_review ON words(next_review_date)");
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_is_mastered ON words(is_mastered)");
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_deleted_at ON words(deleted_at)");
    }

    // ────────── Internal helpers ──────────

    private ContentValues valuesFor(Word w) {
        ContentValues values = new ContentValues();
        values.put("word", w.word);
        values.put("phonetic", w.phonetic);
        values.put("part_of_speech", w.partOfSpeech);
        values.put("definition", w.definition);
        values.put("english_definition", w.englishDefinition);
        values.put("examples_json", w.examplesJson == null || w.examplesJson.isEmpty() ? "[]" : w.examplesJson);
        values.put("synonyms_json", w.synonymsJson == null || w.synonymsJson.isEmpty() ? "[]" : w.synonymsJson);
        values.put("notes", w.notes);
        values.put("review_stage", w.reviewStage);
        values.put("next_review_date", w.nextReviewDate);
        values.put("total_reviews", w.totalReviews);
        values.put("correct_reviews", w.correctReviews);
        values.put("created_at", w.createdAt == null || w.createdAt.isEmpty() ? Utils.nowIso() : w.createdAt);
        values.put("last_reviewed_at", w.lastReviewedAt);
        values.put("is_mastered", w.mastered ? 1 : 0);
        values.put("updated_at", w.updatedAt == null || w.updatedAt.isEmpty() ? Utils.nowIso() : w.updatedAt);
        values.put("deleted_at", w.deletedAt == null ? "" : w.deletedAt);
        return values;
    }

    private void migrate(SQLiteDatabase db) {
        addColumnIfMissing(db, "english_definition", "TEXT DEFAULT ''");
        addColumnIfMissing(db, "correct_reviews", "INTEGER DEFAULT 0");
        addColumnIfMissing(db, "last_reviewed_at", "TEXT DEFAULT ''");
        addColumnIfMissing(db, "is_mastered", "INTEGER DEFAULT 0");
        addColumnIfMissing(db, "updated_at", "TEXT DEFAULT ''");
        addColumnIfMissing(db, "deleted_at", "TEXT DEFAULT ''");

        // Fix NULL deleted_at ? SQLite ALTER TABLE DEFAULT only applies to new rows
        try {
            db.execSQL("UPDATE words SET deleted_at = '' WHERE deleted_at IS NULL");
        } catch (Exception ignored) {}
        try {
            db.execSQL("CREATE INDEX IF NOT EXISTS idx_deleted_at ON words(deleted_at)");
        } catch (Exception ignored) {}
    }

    private void addColumnIfMissing(SQLiteDatabase db, String col, String def) {
        try (Cursor c = db.rawQuery("PRAGMA table_info(words)", null)) {
            while (c.moveToNext()) {
                if (col.equals(c.getString(1))) {
                    return;
                }
            }
        }
        db.execSQL("ALTER TABLE words ADD COLUMN " + col + " " + def);
    }

    private List<Word> readWords(Cursor c) {
        ArrayList<Word> out = new ArrayList<>();
        while (c.moveToNext()) {
            Word w = new Word();
            w.id = colInt(c, "id");
            w.word = colString(c, "word");
            w.phonetic = colString(c, "phonetic");
            w.partOfSpeech = colString(c, "part_of_speech");
            w.definition = colString(c, "definition");
            w.englishDefinition = colString(c, "english_definition");
            w.examplesJson = colString(c, "examples_json");
            w.synonymsJson = colString(c, "synonyms_json");
            w.notes = colString(c, "notes");
            w.reviewStage = colInt(c, "review_stage");
            w.nextReviewDate = colString(c, "next_review_date");
            w.totalReviews = colInt(c, "total_reviews");
            w.correctReviews = colInt(c, "correct_reviews");
            w.createdAt = colString(c, "created_at");
            w.lastReviewedAt = colString(c, "last_reviewed_at");
            w.mastered = colInt(c, "is_mastered") == 1;
            w.updatedAt = colString(c, "updated_at");
            w.deletedAt = colString(c, "deleted_at");
            out.add(w);
        }
        return out;
    }

    private String colString(Cursor c, String name) {
        int idx = c.getColumnIndex(name);
        return idx >= 0 && !c.isNull(idx) ? c.getString(idx) : "";
    }

    private int colInt(Cursor c, String name) {
        int idx = c.getColumnIndex(name);
        return idx >= 0 && !c.isNull(idx) ? c.getInt(idx) : 0;
    }
}
