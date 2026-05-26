package com.wordbuddy.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.graphics.Color;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private SettingsStore settings;
    private WordDbHelper db;
    private LlmClient llm;
    private CosSyncClient sync;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private LinearLayout root;
    private TextView status;
    private EditText searchInput;
    private final ArrayList<Word> reviewQueue = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        settings = new SettingsStore(this);
        db = new WordDbHelper(this);
        llm = new LlmClient(settings);
        sync = new CosSyncClient(this, settings);
        showHome();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        io.shutdownNow();
        db.close();
    }

    private void showHome() {
        root = base("WordBuddy");
        status = label("", 14, "#475569");
        root.addView(status);

        LinearLayout actions = row();
        actions.addView(rowButton("查词", v -> showQuery()));
        actions.addView(rowButton("今日复习", v -> startDueReview()));
        root.addView(actions);

        LinearLayout actions2 = row();
        actions2.addView(rowButton("随机复习", v -> startRandomReview()));
        actions2.addView(rowButton("词库", v -> showLibrary("")));
        root.addView(actions2);

        LinearLayout actions3 = row();
        actions3.addView(rowButton("立即同步", v -> runSync()));
        actions3.addView(rowButton("设置", v -> showSettings()));
        root.addView(actions3);

        refreshStats();
    }

    private void showQuery() {
        root = base("查词");
        EditText input = input("输入英文单词或短语", false);
        root.addView(input);
        root.addView(button("AI 查词并加入词库", v -> {
            hideKeyboard(input);
            String word = input.getText().toString().trim();
            if (word.isEmpty()) {
                toast("请输入单词");
                return;
            }
            runBusy("查词中...", () -> {
                JSONObject data = llm.queryWord(word);
                db.addOrUpdateFromJson(data);
                tryUploadAfterChange();
                return "已加入词库：" + data.optString("word", word);
            }, this::showHome);
        }));
        root.addView(button("手动加入空词条", v -> {
            try {
                db.addManualWord(input.getText().toString());
                tryUploadAfterChange();
                toast("已加入词库");
                showHome();
            } catch (Exception e) {
                toast(e.getMessage());
            }
        }));
        root.addView(button("返回", v -> showHome()));
    }

    private void showLibrary(String query) {
        root = base("词库");
        searchInput = input("搜索单词或释义", false);
        searchInput.setText(query);
        root.addView(searchInput);
        root.addView(button("搜索", v -> showLibrary(searchInput.getText().toString())));

        List<Word> words = db.allWords(query);
        if (words.isEmpty()) {
            root.addView(label("没有找到词条", 16, "#64748B"));
        }
        for (Word w : words) {
            TextView item = label(wordSummary(w), 16, "#0F172A");
            item.setPadding(0, dp(12), 0, dp(12));
            item.setOnClickListener(v -> showWordDetail(w.id));
            root.addView(item);
            root.addView(divider());
        }
        root.addView(button("返回", v -> showHome()));
    }

    private void showWordDetail(int id) {
        Word w = db.getById(id);
        if (w == null) {
            showLibrary("");
            return;
        }
        root = base(w.word);
        root.addView(label(w.phonetic + "  " + w.partOfSpeech, 15, "#475569"));
        root.addView(label(w.definition, 18, "#0F172A"));
        if (!w.englishDefinition.isEmpty()) {
            root.addView(label(w.englishDefinition, 15, "#334155"));
        }
        for (String ex : w.examples()) {
            root.addView(label("- " + ex, 15, "#334155"));
        }
        root.addView(label("阶段 " + w.reviewStage + "，下次复习 " + (w.nextReviewDate.isEmpty() ? "已掌握" : w.nextReviewDate), 14, "#64748B"));
        root.addView(button("删除", v -> confirmDelete(w.id)));
        root.addView(button("返回词库", v -> showLibrary(searchInput == null ? "" : searchInput.getText().toString())));
    }

    private void confirmDelete(int id) {
        new AlertDialog.Builder(this)
                .setTitle("删除词条")
                .setMessage("确定删除这个单词吗？")
                .setNegativeButton("取消", null)
                .setPositiveButton("删除", (d, which) -> {
                    db.deleteWord(id);
                    tryUploadAfterChange();
                    showLibrary("");
                })
                .show();
    }

    private void startDueReview() {
        reviewQueue.clear();
        reviewQueue.addAll(db.dueWords());
        showNextReview();
    }

    private void startRandomReview() {
        reviewQueue.clear();
        reviewQueue.addAll(db.randomLearningWords(10));
        showNextReview();
    }

    private void showNextReview() {
        if (reviewQueue.isEmpty()) {
            toast("没有待复习单词");
            showHome();
            return;
        }
        Word w = reviewQueue.get(0);
        root = base("复习");
        root.addView(label(w.word, 34, "#0F172A"));
        root.addView(label(w.phonetic, 16, "#475569"));
        root.addView(label(w.definition, 20, "#0F172A"));
        if (!w.englishDefinition.isEmpty()) {
            root.addView(label(w.englishDefinition, 15, "#334155"));
        }
        for (String ex : w.examples()) {
            root.addView(label("- " + ex, 15, "#334155"));
        }
        LinearLayout actions = row();
        actions.addView(rowButton("记住", v -> review(w.id, "remembered")));
        actions.addView(rowButton("模糊", v -> review(w.id, "fuzzy")));
        actions.addView(rowButton("忘记", v -> review(w.id, "forgotten")));
        root.addView(actions);
        root.addView(button("结束", v -> showHome()));
    }

    private void review(int id, String result) {
        db.markReviewed(id, result);
        if (!reviewQueue.isEmpty()) {
            reviewQueue.remove(0);
        }
        tryUploadAfterChange();
        showNextReview();
    }

    private void showSettings() {
        root = base("设置");
        EditText baseUrl = input("LLM Base URL", false);
        baseUrl.setText(settings.llmBaseUrl());
        EditText apiKey = input("LLM API Key", true);
        apiKey.setText(settings.llmApiKey());
        EditText model = input("LLM Model", false);
        model.setText(settings.llmModel());
        EditText secretId = input("COS SecretId", false);
        secretId.setText(settings.cosSecretId());
        EditText secretKey = input("COS SecretKey", true);
        secretKey.setText(settings.cosSecretKey());
        EditText bucket = input("COS Bucket", false);
        bucket.setText(settings.cosBucket());
        EditText region = input("COS Region", false);
        region.setText(settings.cosRegion());

        root.addView(baseUrl);
        root.addView(apiKey);
        root.addView(model);
        root.addView(secretId);
        root.addView(secretKey);
        root.addView(bucket);
        root.addView(region);
        root.addView(button("保存设置", v -> {
            settings.save(
                    baseUrl.getText().toString(),
                    apiKey.getText().toString(),
                    model.getText().toString(),
                    secretId.getText().toString(),
                    secretKey.getText().toString(),
                    bucket.getText().toString(),
                    region.getText().toString()
            );
            toast("已保存");
            showHome();
        }));
        root.addView(button("返回", v -> showHome()));
    }

    private void runSync() {
        runBusy("同步中...", () -> sync.sync(db, this), this::showHome);
    }

    private void tryUploadAfterChange() {
        if (!settings.hasCos()) {
            return;
        }
        io.submit(() -> {
            try {
                sync.sync(db, this);
            } catch (Exception ignored) {
            }
        });
    }

    private void refreshStats() {
        int total = db.count("", null);
        int mastered = db.count("WHERE is_mastered = 1", null);
        int due = db.count("WHERE is_mastered = 0 AND next_review_date != '' AND next_review_date <= ?",
                new String[]{Utils.today()});
        status.setText("总词数 " + total + "  |  已掌握 " + mastered + "  |  今日待复习 " + due);
    }

    private String wordSummary(Word w) {
        String def = w.definition == null ? "" : w.definition;
        if (def.length() > 52) {
            def = def.substring(0, 52) + "...";
        }
        return w.word + "\n" + def;
    }

    private interface Task {
        String run() throws Exception;
    }

    private void runBusy(String busy, Task task, Runnable afterOk) {
        toast(busy);
        io.submit(() -> {
            try {
                String msg = task.run();
                runOnUiThread(() -> {
                    toast(msg);
                    afterOk.run();
                });
            } catch (Exception e) {
                runOnUiThread(() -> toast(e.getMessage() == null ? "操作失败" : e.getMessage()));
            }
        });
    }

    private LinearLayout base(String title) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(18), dp(20), dp(28));
        scroll.addView(box);
        setContentView(scroll);
        TextView h = label(title, 28, "#0F172A");
        h.setGravity(Gravity.START);
        h.setPadding(0, 0, 0, dp(12));
        box.addView(h);
        return box;
    }

    private LinearLayout row() {
        LinearLayout r = new LinearLayout(this);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER);
        r.setPadding(0, dp(8), 0, dp(2));
        return r;
    }

    private Button button(String text, View.OnClickListener listener) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setOnClickListener(listener);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(48)
        );
        lp.setMargins(dp(4), dp(4), dp(4), dp(4));
        b.setLayoutParams(lp);
        return b;
    }

    private Button rowButton(String text, View.OnClickListener listener) {
        Button b = button(text, listener);
        b.setLayoutParams(new LinearLayout.LayoutParams(0, dp(48), 1));
        return b;
    }

    private EditText input(String hint, boolean password) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setSingleLine(true);
        e.setInputType(password
                ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                : InputType.TYPE_CLASS_TEXT);
        e.setPadding(0, dp(10), 0, dp(10));
        e.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));
        return e;
    }

    private TextView label(String text, int sp, String color) {
        TextView tv = new TextView(this);
        tv.setText(text == null ? "" : text);
        tv.setTextSize(sp);
        tv.setTextColor(Color.parseColor(color));
        tv.setLineSpacing(0, 1.15f);
        tv.setPadding(0, dp(4), 0, dp(4));
        return tv;
    }

    private View divider() {
        View v = new View(this);
        v.setBackgroundColor(Color.parseColor("#E2E8F0"));
        v.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                Math.max(1, dp(1))
        ));
        return v;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show();
    }

    private void hideKeyboard(View view) {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) {
            imm.hideSoftInputFromWindow(view.getWindowToken(), 0);
        }
    }
}
