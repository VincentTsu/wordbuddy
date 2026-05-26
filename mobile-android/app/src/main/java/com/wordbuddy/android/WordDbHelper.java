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

    List<Word> dueWords() {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE is_mastered = 0 AND next_review_date != '' "
                        + "AND next_review_date <= ? ORDER BY RANDOM()",
                new String[]{Utils.today()})) {
            return readWords(c);
        }
    }

    List<Word> randomLearningWords(int count) {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE is_mastered = 0 ORDER BY RANDOM() LIMIT ?",
                new String[]{String.valueOf(count)})) {
            return readWords(c);
        }
    }

    List<Word> allWords(String search) {
        SQLiteDatabase db = getReadableDatabase();
        String s = search == null ? "" : search.trim();
        if (s.isEmpty()) {
            try (Cursor c = db.rawQuery("SELECT * FROM words ORDER BY created_at DESC LIMIT 200", null)) {
                return readWords(c);
            }
        }
        String like = "%" + s + "%";
        try (Cursor c = db.rawQuery(
                "SELECT * FROM words WHERE word LIKE ? OR definition LIKE ? ORDER BY created_at DESC LIMIT 200",
                new String[]{like, like})) {
            return readWords(c);
        }
    }

    int count(String where, String[] args) {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery("SELECT COUNT(*) FROM words " + where, args)) {
            return c.moveToFirst() ? c.getInt(0) : 0;
        }
    }

    Word getById(int id) {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery("SELECT * FROM words WHERE id = ?", new String[]{String.valueOf(id)})) {
            List<Word> words = readWords(c);
            return words.isEmpty() ? null : words.get(0);
        }
    }

    void addOrUpdateFromJson(JSONObject data) throws Exception {
        String wordText = data.optString("word").trim();
        if (wordText.isEmpty()) {
            throw new IllegalArgumentException("单词不能为空");
        }
        SQLiteDatabase db = getWritableDatabase();
        ContentValues values = new ContentValues();
        values.put("word", wordText);
        values.put("phonetic", data.optString("phonetic"));
        values.put("part_of_speech", data.optString("part_of_speech"));
        values.put("definition", data.optString("definition"));
        values.put("english_definition", data.optString("english_definition"));
        values.put("examples_json", data.optJSONArray("examples") == null ? "[]" : data.getJSONArray("examples").toString());
        values.put("synonyms_json", data.optJSONArray("synonyms") == null ? "[]" : data.getJSONArray("synonyms").toString());
        values.put("notes", data.optString("notes"));

        try (Cursor c = db.rawQuery("SELECT id FROM words WHERE word = ? COLLATE NOCASE", new String[]{wordText})) {
            if (c.moveToFirst()) {
                db.update("words", values, "word = ? COLLATE NOCASE", new String[]{wordText});
                return;
            }
        }

        values.put("review_stage", 0);
        values.put("next_review_date", Utils.dateAfterDays(Constants.REVIEW_INTERVALS[0]));
        values.put("created_at", Utils.nowIso());
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
        Word word = getById(id);
        if (word == null) {
            return;
        }
        int newStage;
        if ("remembered".equals(result)) {
            newStage = Math.min(word.reviewStage + 1, Constants.REVIEW_INTERVALS.length);
        } else if ("fuzzy".equals(result)) {
            newStage = word.reviewStage;
        } else {
            newStage = Math.max(word.reviewStage - 1, 0);
        }

        boolean mastered = newStage >= Constants.REVIEW_INTERVALS.length;
        String nextReview = "";
        if (!mastered) {
            nextReview = "fuzzy".equals(result)
                    ? Utils.dateAfterDays(1)
                    : Utils.dateAfterDays(Constants.REVIEW_INTERVALS[newStage]);
        }

        ContentValues values = new ContentValues();
        values.put("review_stage", newStage);
        values.put("next_review_date", nextReview);
        values.put("is_mastered", mastered ? 1 : 0);
        values.put("total_reviews", word.totalReviews + 1);
        values.put("correct_reviews", word.correctReviews + ("remembered".equals(result) ? 1 : 0));
        values.put("last_reviewed_at", Utils.nowIso());
        getWritableDatabase().update("words", values, "id = ?", new String[]{String.valueOf(id)});
    }

    void deleteWord(int id) {
        getWritableDatabase().delete("words", "id = ?", new String[]{String.valueOf(id)});
    }

    int mergeFrom(File otherDbFile) {
        SQLiteDatabase remote = SQLiteDatabase.openDatabase(
                otherDbFile.getAbsolutePath(),
                null,
                SQLiteDatabase.OPEN_READONLY
        );
        int changed = 0;
        try (Cursor c = remote.rawQuery("SELECT * FROM words", null)) {
            for (Word remoteWord : readWords(c)) {
                Word localWord = getByText(remoteWord.word);
                if (localWord == null) {
                    getWritableDatabase().insertOrThrow("words", null, valuesFor(remoteWord));
                    changed++;
                } else if (shouldPreferRemote(localWord, remoteWord)) {
                    getWritableDatabase().update(
                            "words",
                            valuesFor(remoteWord),
                            "word = ? COLLATE NOCASE",
                            new String[]{remoteWord.word}
                    );
                    changed++;
                }
            }
        } finally {
            remote.close();
        }
        return changed;
    }

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
                + "is_mastered INTEGER DEFAULT 0"
                + ")");
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_next_review ON words(next_review_date)");
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_is_mastered ON words(is_mastered)");
    }

    private Word getByText(String word) {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery("SELECT * FROM words WHERE word = ? COLLATE NOCASE", new String[]{word})) {
            List<Word> words = readWords(c);
            return words.isEmpty() ? null : words.get(0);
        }
    }

    private boolean shouldPreferRemote(Word local, Word remote) {
        if (local.definition.isEmpty() && !remote.definition.isEmpty()) {
            return true;
        }
        if (remote.lastReviewedAt.compareTo(local.lastReviewedAt) > 0) {
            return true;
        }
        return remote.totalReviews > local.totalReviews;
    }

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
        return values;
    }

    private void migrate(SQLiteDatabase db) {
        addColumnIfMissing(db, "english_definition", "TEXT DEFAULT ''");
        addColumnIfMissing(db, "correct_reviews", "INTEGER DEFAULT 0");
        addColumnIfMissing(db, "last_reviewed_at", "TEXT DEFAULT ''");
        addColumnIfMissing(db, "is_mastered", "INTEGER DEFAULT 0");
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
