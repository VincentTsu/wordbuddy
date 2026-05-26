package com.wordbuddy.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
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
import java.util.Stack;
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
    private final Stack<Runnable> backStack = new Stack<>();
    private String lastLibrarySearch = "";
    private Runnable wordDetailBack = null;
    private int fillRatio = 25;
    private boolean currentReviewIsFill = false;
    private Word currentReviewWord = null;
    private EditText fillInput = null;
    private TextView fillResultLabel = null;
    private Button fillCheckBtn = null;
    private LinearLayout fillWidget = null;
    private LinearLayout normalWidget = null;

    // Color palette
    private static final String PRIMARY = "#6366F1";
    private static final String PRIMARY_DARK = "#4F46E5";
    private static final String GREEN = "#10B981";
    private static final String AMBER = "#F59E0B";
    private static final String RED = "#EF4444";
    private static final String BG = "#F8FAFC";
    private static final String SURFACE = "#FFFFFF";
    private static final String TEXT_MAIN = "#1E293B";
    private static final String TEXT_SUB = "#64748B";
    private static final String TEXT_LIGHT = "#94A3B8";
    private static final String BORDER = "#E2E8F0";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        settings = new SettingsStore(this);
        db = new WordDbHelper(this);
        llm = new LlmClient(settings);
        sync = new CosSyncClient(this, settings);
        fillRatio = settings.fillRatio();
        showHome();
        // Startup sync: pull cloud words in background
        if (settings.hasCos()) {
            io.submit(() -> {
                try {
                    String msg = sync.sync(db, this);
                    runOnUiThread(() -> toast("云端同步: " + msg));
                } catch (Exception e) {
                    // silent — cloud sync is best-effort on startup
                }
            });
        }
    }

    @Override
    public void onBackPressed() {
        if (!backStack.isEmpty()) {
            backStack.pop().run();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        io.shutdownNow();
        db.close();
    }

    // ═══════════════════ HOME ═══════════════════

    private void showHome() {
        backStack.clear();
        ScrollView scroll = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(0, 0, 0, dp(32));
        scroll.addView(box);
        setContentView(scroll);

        // Header
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(dp(24), dp(48), dp(24), dp(28));
        header.setBackgroundColor(Color.parseColor(PRIMARY));
        box.addView(header);

        TextView title = new TextView(this);
        title.setText("WordBuddy");
        title.setTextSize(30);
        title.setTextColor(Color.WHITE);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        header.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("英语词汇学习助手");
        subtitle.setTextSize(15);
        subtitle.setTextColor(Color.parseColor("#C7D2FE"));
        subtitle.setPadding(0, dp(6), 0, dp(20));
        header.addView(subtitle);

        // Stats card
        LinearLayout statsCard = new LinearLayout(this);
        statsCard.setOrientation(LinearLayout.HORIZONTAL);
        statsCard.setGravity(Gravity.CENTER);
        statsCard.setPadding(dp(16), dp(14), dp(16), dp(14));
        GradientDrawable statsBg = new GradientDrawable();
        statsBg.setCornerRadius(dp(12));
        statsBg.setColor(Color.parseColor("#EEF2FF"));
        statsCard.setBackground(statsBg);
        header.addView(statsCard);

        int total = db.count("", null);
        int mastered = db.count("WHERE is_mastered = 1", null);
        int due = db.count("WHERE is_mastered = 0 AND next_review_date != '' AND next_review_date <= ?",
                new String[]{Utils.today()});

        statsCard.addView(statItem(String.valueOf(total), "总词数", PRIMARY));
        statsCard.addView(statDivider());
        LinearLayout masteredStat = statItem(String.valueOf(mastered), "已掌握", GREEN);
        masteredStat.setClickable(true);
        masteredStat.setOnClickListener(v -> showMastered());
        statsCard.addView(masteredStat);
        statsCard.addView(statDivider());
        statsCard.addView(statItem(String.valueOf(due), "待复习", due > 0 ? RED : TEXT_SUB));

        // Menu section
        LinearLayout menu = new LinearLayout(this);
        menu.setOrientation(LinearLayout.VERTICAL);
        menu.setPadding(dp(16), dp(20), dp(16), 0);
        box.addView(menu);

        menu.addView(sectionLabel("功能"));

        LinearLayout row1 = new LinearLayout(this);
        row1.setOrientation(LinearLayout.HORIZONTAL);
        row1.addView(homeCard("🔍", "查词", "AI 智能查询", v -> showQuery()));
        row1.addView(homeCard("📚", "今日复习", due + " 个待复习", v -> startDueReview()));
        menu.addView(row1);

        LinearLayout row2 = new LinearLayout(this);
        row2.setOrientation(LinearLayout.HORIZONTAL);
        row2.addView(homeCard("🎲", "随机复习", "随机 10 个词", v -> startRandomReview()));
        row2.addView(homeCard("📋", "词库", total + " 个单词", v -> showLibrary("")));
        menu.addView(row2);

        menu.addView(sectionLabel("数据"));

        LinearLayout row3 = new LinearLayout(this);
        row3.setOrientation(LinearLayout.HORIZONTAL);
        row3.addView(homeCard("☁️", "立即同步", "与云端同步", v -> runSync()));
        row3.addView(homeCard("⚙️", "设置", "API 与 COS 配置", v -> showSettings()));
        menu.addView(row3);
    }

    private LinearLayout statItem(String value, String label, String color) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER);
        col.setLayoutParams(new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));

        TextView v = new TextView(this);
        v.setText(value);
        v.setTextSize(22);
        v.setTextColor(Color.parseColor(color));
        v.setTypeface(null, android.graphics.Typeface.BOLD);
        v.setGravity(Gravity.CENTER);
        col.addView(v);

        TextView l = new TextView(this);
        l.setText(label);
        l.setTextSize(12);
        l.setTextColor(Color.parseColor(TEXT_SUB));
        l.setGravity(Gravity.CENTER);
        l.setPadding(0, dp(2), 0, 0);
        col.addView(l);
        return col;
    }

    private View statDivider() {
        View d = new View(this);
        d.setBackgroundColor(Color.parseColor("#CBD5E1"));
        d.setLayoutParams(new LinearLayout.LayoutParams(dp(1), dp(36)));
        return d;
    }

    private LinearLayout homeCard(String icon, String title, String desc, View.OnClickListener listener) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(16), dp(16), dp(16), dp(16));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        lp.setMargins(dp(6), dp(6), dp(6), dp(6));
        card.setLayoutParams(lp);

        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(14));
        bg.setColor(Color.parseColor(SURFACE));
        bg.setStroke(dp(1), Color.parseColor(BORDER));
        card.setBackground(bg);
        card.setClickable(true);
        card.setOnClickListener(listener);

        TextView iconView = new TextView(this);
        iconView.setText(icon);
        iconView.setTextSize(26);
        card.addView(iconView);

        TextView t = new TextView(this);
        t.setText(title);
        t.setTextSize(15);
        t.setTextColor(Color.parseColor(TEXT_MAIN));
        t.setTypeface(null, android.graphics.Typeface.BOLD);
        t.setPadding(0, dp(6), 0, dp(2));
        card.addView(t);

        TextView d = new TextView(this);
        d.setText(desc);
        d.setTextSize(12);
        d.setTextColor(Color.parseColor(TEXT_SUB));
        card.addView(d);

        return card;
    }

    private TextView sectionLabel(String text) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(12);
        t.setTextColor(Color.parseColor(TEXT_LIGHT));
        t.setPadding(dp(6), dp(20), 0, dp(8));
        t.setAllCaps(true);
        return t;
    }

    // ═══════════════════ QUERY ═══════════════════

    private void showQuery() {
        backStack.push(this::showHome);
        root = pageBase("查词");

        LinearLayout inputBox = new LinearLayout(this);
        inputBox.setOrientation(LinearLayout.HORIZONTAL);
        inputBox.setPadding(0, dp(12), 0, dp(16));
        GradientDrawable inputBg = new GradientDrawable();
        inputBg.setCornerRadius(dp(12));
        inputBg.setColor(Color.parseColor(SURFACE));
        inputBg.setStroke(dp(1), Color.parseColor(BORDER));
        inputBox.setBackground(inputBg);
        inputBox.setPadding(dp(4), dp(4), dp(4), dp(4));

        EditText input = new EditText(this);
        input.setHint("输入英文单词或短语");
        input.setSingleLine(true);
        input.setBackgroundColor(Color.TRANSPARENT);
        input.setPadding(dp(12), dp(10), dp(12), dp(10));
        input.setTextSize(16);
        LinearLayout.LayoutParams inputLp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        input.setLayoutParams(inputLp);
        inputBox.addView(input);
        root.addView(inputBox);

        root.addView(primaryButton("AI 查词并加入词库", v -> {
            hideKeyboard(input);
            final String word = input.getText().toString().trim();
            if (word.isEmpty()) { toast("请输入单词"); return; }
            runBusy("查词中...", () -> {
                JSONObject data = llm.queryWord(word);
                db.addOrUpdateFromJson(data);
                tryUploadAfterChange();
                return word;
            }, () -> {
                Word w = db.getByText(word);
                if (w != null) {
                    wordDetailBack = this::showQuery;
                    showWordDetail(w.id);
                }
            });
        }));
        root.addView(ghostButton("返回首页", v -> showHome()));
    }

    // ═══════════════════ LIBRARY ═══════════════════

    private void showLibrary(String query) {
        backStack.push(this::showHome);
        lastLibrarySearch = query != null ? query : "";
        root = pageBase("词库");

        LinearLayout searchBox = new LinearLayout(this);
        searchBox.setOrientation(LinearLayout.HORIZONTAL);
        GradientDrawable sbBg = new GradientDrawable();
        sbBg.setCornerRadius(dp(12));
        sbBg.setColor(Color.parseColor(SURFACE));
        sbBg.setStroke(dp(1), Color.parseColor(BORDER));
        searchBox.setBackground(sbBg);
        searchBox.setPadding(dp(4), dp(4), dp(4), dp(4));

        searchInput = new EditText(this);
        searchInput.setHint("搜索单词或释义");
        searchInput.setSingleLine(true);
        searchInput.setText(query);
        searchInput.setBackgroundColor(Color.TRANSPARENT);
        searchInput.setPadding(dp(12), dp(10), dp(12), dp(10));
        searchInput.setTextSize(15);
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        searchInput.setLayoutParams(slp);
        searchBox.addView(searchInput);

        Button searchBtn = new Button(this);
        searchBtn.setText("搜索");
        searchBtn.setAllCaps(false);
        searchBtn.setTextColor(Color.WHITE);
        searchBtn.setTextSize(14);
        GradientDrawable sbtnBg = new GradientDrawable();
        sbtnBg.setCornerRadius(dp(10));
        sbtnBg.setColor(Color.parseColor(PRIMARY));
        searchBtn.setBackground(sbtnBg);
        searchBtn.setPadding(dp(20), 0, dp(20), 0);
        searchBtn.setLayoutParams(new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(40)));
        searchBtn.setOnClickListener(v -> showLibrary(searchInput.getText().toString()));
        searchBox.addView(searchBtn);
        root.addView(searchBox);

        View spacer = new View(this);
        spacer.setLayoutParams(new LinearLayout.LayoutParams(1, dp(14)));
        root.addView(spacer);

        List<Word> words = db.allWords(query);
        if (words.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText("没有找到词条");
            empty.setTextSize(15);
            empty.setTextColor(Color.parseColor(TEXT_SUB));
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, dp(48), 0, 0);
            root.addView(empty);
        }
        for (Word w : words) {
            final int wordId = w.id;
            Runnable backToLibrary = () -> showLibrary(lastLibrarySearch);
            root.addView(wordCard(w, backToLibrary));
        }
        root.addView(ghostButton("返回首页", v -> showHome()));
    }

    private LinearLayout wordCard(Word w, Runnable backAction) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(16), dp(14), dp(16), dp(14));
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        clp.setMargins(0, 0, 0, dp(8));
        card.setLayoutParams(clp);

        GradientDrawable cardBg = new GradientDrawable();
        cardBg.setCornerRadius(dp(12));
        cardBg.setColor(Color.parseColor(SURFACE));
        cardBg.setStroke(dp(1), Color.parseColor(BORDER));
        card.setBackground(cardBg);
        card.setClickable(true);
        card.setOnClickListener(v -> {
            wordDetailBack = backAction;
            showWordDetail(w.id);
        });

        LinearLayout topRow = new LinearLayout(this);
        topRow.setOrientation(LinearLayout.HORIZONTAL);
        topRow.setGravity(Gravity.CENTER_VERTICAL);

        TextView wordView = new TextView(this);
        wordView.setText(w.word);
        wordView.setTextSize(17);
        wordView.setTextColor(Color.parseColor(TEXT_MAIN));
        wordView.setTypeface(null, android.graphics.Typeface.BOLD);
        topRow.addView(wordView);

        // Review stage badge
        if (w.reviewStage >= 6) {
            topRow.addView(badge("已掌握", GREEN));
        } else if (w.reviewStage > 0) {
            topRow.addView(badge("Lv." + w.reviewStage, PRIMARY));
        }
        card.addView(topRow);

        String def = w.definition;
        if (def != null && !def.isEmpty()) {
            if (def.length() > 60) def = def.substring(0, 60) + "...";
            TextView defView = new TextView(this);
            defView.setText(def);
            defView.setTextSize(14);
            defView.setTextColor(Color.parseColor(TEXT_SUB));
            defView.setPadding(0, dp(6), 0, 0);
            card.addView(defView);
        }
        return card;
    }

    private TextView badge(String text, String color) {
        TextView b = new TextView(this);
        b.setText(text);
        b.setTextSize(11);
        b.setTextColor(Color.parseColor(color));
        b.setPadding(dp(8), dp(2), dp(8), dp(3));
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        blp.setMargins(dp(8), 0, 0, 0);
        b.setLayoutParams(blp);
        GradientDrawable bbg = new GradientDrawable();
        bbg.setCornerRadius(dp(10));
        String bgColor = color + "1A"; // 10% opacity
        bbg.setColor(Color.parseColor(bgColor));
        b.setBackground(bbg);
        return b;
    }

    // ═══════════════════ WORD DETAIL ═══════════════════

    private void showWordDetail(int id) {
        Word w = db.getById(id);
        if (w == null) { showLibrary(""); return; }
        final Runnable back = wordDetailBack != null ? wordDetailBack : () -> showLibrary(lastLibrarySearch);
        wordDetailBack = null;
        backStack.push(back);
        root = pageBase(w.word);

        // Phonetic & POS
        root.addView(bodyText(w.phonetic + "  " + w.partOfSpeech, 15, TEXT_SUB));
        View spacer1 = new View(this);
        spacer1.setLayoutParams(new LinearLayout.LayoutParams(1, dp(14)));
        root.addView(spacer1);

        // Definition
        root.addView(bodyText(w.definition, 20, TEXT_MAIN));

        // English definition
        if (!w.englishDefinition.isEmpty()) {
            root.addView(bodyText(w.englishDefinition, 15, TEXT_SUB));
        }

        // Examples
        if (!w.examples().isEmpty()) {
            View spacer2 = new View(this);
            spacer2.setLayoutParams(new LinearLayout.LayoutParams(1, dp(12)));
            root.addView(spacer2);
            TextView exLabel = new TextView(this);
            exLabel.setText("例句");
            exLabel.setTextSize(12);
            exLabel.setTextColor(Color.parseColor(TEXT_LIGHT));
            exLabel.setAllCaps(true);
            exLabel.setPadding(0, 0, 0, dp(6));
            root.addView(exLabel);
            for (String ex : w.examples()) {
                root.addView(bodyText("  " + ex, 14, TEXT_SUB));
            }
        }

        // Review info
        View spacer3 = new View(this);
        spacer3.setLayoutParams(new LinearLayout.LayoutParams(1, dp(16)));
        root.addView(spacer3);

        LinearLayout infoCard = new LinearLayout(this);
        infoCard.setOrientation(LinearLayout.VERTICAL);
        infoCard.setPadding(dp(14), dp(12), dp(14), dp(12));
        GradientDrawable infoBg = new GradientDrawable();
        infoBg.setCornerRadius(dp(10));
        infoBg.setColor(Color.parseColor("#F1F5F9"));
        infoCard.setBackground(infoBg);

        String reviewInfo = "复习阶段 " + w.reviewStage + "/6";
        if (w.reviewStage >= 6) reviewInfo = "已完全掌握";
        else if (!w.nextReviewDate.isEmpty()) reviewInfo += "  ·  下次复习 " + w.nextReviewDate;
        if (w.totalReviews > 0) reviewInfo += "  ·  共复习 " + w.totalReviews + " 次";
        infoCard.addView(bodyText(reviewInfo, 13, TEXT_SUB));
        root.addView(infoCard);

        View spacer4 = new View(this);
        spacer4.setLayoutParams(new LinearLayout.LayoutParams(1, dp(16)));
        root.addView(spacer4);

        root.addView(dangerButton("删除此词条", v -> confirmDelete(w.id, w.word)));
        root.addView(ghostButton("返回", v -> back.run()));
    }

    private void confirmDelete(int id, String word) {
        new AlertDialog.Builder(this)
                .setTitle("删除词条")
                .setMessage("确定删除这个单词吗？此操作不可撤销。")
                .setNegativeButton("取消", null)
                .setPositiveButton("删除", (d, which) -> {
                    db.deleteWord(id);
                    tryUploadAfterChange();
                    showLibrary("");
                })
                .show();
    }

    // ═══════════════════ REVIEW ═══════════════════

    private void startDueReview() {
        backStack.push(this::showHome);
        reviewQueue.clear();
        reviewQueue.addAll(db.dueWords());
        showNextReview();
    }

    private void startRandomReview() {
        backStack.push(this::showHome);
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
        currentReviewWord = w;

        currentReviewIsFill = fillRatio > 0 && new java.util.Random().nextInt(100) < fillRatio;

        ScrollView scroll = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(48), dp(24), dp(32));
        scroll.addView(box);
        setContentView(scroll);

        TextView progress = new TextView(this);
        progress.setText("复习中 · 剩余 " + reviewQueue.size() + " 个");
        progress.setTextSize(13);
        progress.setTextColor(Color.parseColor(TEXT_LIGHT));
        box.addView(progress);

        LinearLayout wordHeader = new LinearLayout(this);
        wordHeader.setOrientation(LinearLayout.VERTICAL);
        wordHeader.setPadding(0, dp(24), 0, dp(8));
        box.addView(wordHeader);

        TextView wordView = new TextView(this);
        wordView.setText(w.word);
        wordView.setTextSize(36);
        wordView.setTextColor(Color.parseColor(TEXT_MAIN));
        wordView.setTypeface(null, android.graphics.Typeface.BOLD);
        wordHeader.addView(wordView);

        String subtitle = w.phonetic;
        if (!w.partOfSpeech.isEmpty()) subtitle += "  ·  " + w.partOfSpeech;
        TextView sub = new TextView(this);
        sub.setText(subtitle);
        sub.setTextSize(15);
        sub.setTextColor(Color.parseColor(TEXT_SUB));
        sub.setPadding(0, dp(4), 0, 0);
        wordHeader.addView(sub);
        if (currentReviewIsFill) {
            wordHeader.setVisibility(View.GONE);
        }

        // === Normal mode widget ===
        normalWidget = new LinearLayout(this);
        normalWidget.setOrientation(LinearLayout.VERTICAL);
        box.addView(normalWidget);

        LinearLayout defCard = new LinearLayout(this);
        defCard.setOrientation(LinearLayout.VERTICAL);
        defCard.setPadding(dp(20), dp(20), dp(20), dp(20));
        defCard.setGravity(Gravity.CENTER);
        GradientDrawable defBg = new GradientDrawable();
        defBg.setCornerRadius(dp(16));
        defBg.setColor(Color.parseColor("#EEF2FF"));
        defCard.setBackground(defBg);
        normalWidget.addView(defCard);

        TextView hint = new TextView(this);
        hint.setText("轻触查看释义");
        hint.setTextSize(14);
        hint.setTextColor(Color.parseColor(PRIMARY));
        defCard.addView(hint);

        TextView defView = new TextView(this);
        defView.setText(w.definition);
        defView.setTextSize(20);
        defView.setTextColor(Color.parseColor(TEXT_MAIN));
        defView.setTypeface(null, android.graphics.Typeface.BOLD);
        defView.setGravity(Gravity.CENTER);
        defView.setVisibility(View.GONE);
        defCard.addView(defView);

        final boolean[] revealed = {false};
        defCard.setClickable(true);
        defCard.setOnClickListener(v -> {
            if (!revealed[0]) {
                hint.setVisibility(View.GONE);
                defView.setVisibility(View.VISIBLE);
                revealed[0] = true;
                if (!w.englishDefinition.isEmpty()) {
                    TextView engDef = new TextView(MainActivity.this);
                    engDef.setText(w.englishDefinition);
                    engDef.setTextSize(14);
                    engDef.setTextColor(Color.parseColor(TEXT_SUB));
                    engDef.setGravity(Gravity.CENTER);
                    engDef.setPadding(0, dp(8), 0, 0);
                    defCard.addView(engDef);
                }
                for (String ex : w.examples()) {
                    TextView exView = new TextView(MainActivity.this);
                    exView.setText(ex);
                    exView.setTextSize(13);
                    exView.setTextColor(Color.parseColor(TEXT_SUB));
                    exView.setGravity(Gravity.CENTER);
                    exView.setPadding(0, dp(4), 0, 0);
                    defCard.addView(exView);
                }
            }
        });

        View spacer5 = new View(this);
        spacer5.setLayoutParams(new LinearLayout.LayoutParams(1, dp(28)));
        normalWidget.addView(spacer5);

        TextView actionLabel = new TextView(this);
        actionLabel.setText("你记住了吗？");
        actionLabel.setTextSize(13);
        actionLabel.setTextColor(Color.parseColor(TEXT_LIGHT));
        actionLabel.setGravity(Gravity.CENTER);
        actionLabel.setAllCaps(true);
        actionLabel.setPadding(0, 0, 0, dp(12));
        normalWidget.addView(actionLabel);

        normalWidget.addView(reviewButton("记住了", "#059669", v -> review(currentReviewWord.id, "remembered")));
        normalWidget.addView(reviewButton("有点模糊", "#6366F1", v -> review(currentReviewWord.id, "fuzzy")));
        normalWidget.addView(reviewButton("没记住", "#94A3B8", v -> review(currentReviewWord.id, "forgotten")));

        // === Fill mode widget ===
        fillWidget = new LinearLayout(this);
        fillWidget.setOrientation(LinearLayout.VERTICAL);
        fillWidget.setVisibility(View.GONE);
        box.addView(fillWidget);

        TextView fillDefLabel = new TextView(this);
        fillDefLabel.setText("释义:");
        fillDefLabel.setTextSize(13);
        fillDefLabel.setTextColor(Color.parseColor(TEXT_LIGHT));
        fillDefLabel.setPadding(0, dp(20), 0, dp(6));
        fillWidget.addView(fillDefLabel);

        String defn = w.definition.isEmpty() ? w.englishDefinition : w.definition;
        TextView fillDef = new TextView(this);
        fillDef.setText(defn);
        fillDef.setTextSize(22);
        fillDef.setTextColor(Color.parseColor(TEXT_MAIN));
        fillDef.setTypeface(null, android.graphics.Typeface.BOLD);
        fillWidget.addView(fillDef);

        java.util.List<String> examples = w.examples();
        if (!examples.isEmpty()) {
            String sentence = examples.get(0);
            String blanked = sentence.replaceFirst("(?i)\\b" + java.util.regex.Pattern.quote(w.word) + "\\b", "______");
            View sp = new View(this);
            sp.setLayoutParams(new LinearLayout.LayoutParams(1, dp(16)));
            fillWidget.addView(sp);
            TextView fillSentenceLabel = new TextView(this);
            fillSentenceLabel.setText("填空:");
            fillSentenceLabel.setTextSize(13);
            fillSentenceLabel.setTextColor(Color.parseColor(TEXT_LIGHT));
            fillSentenceLabel.setPadding(0, 0, 0, dp(6));
            fillWidget.addView(fillSentenceLabel);
            TextView fillSentence = new TextView(this);
            fillSentence.setText(blanked);
            fillSentence.setTextSize(16);
            fillSentence.setTextColor(Color.parseColor(TEXT_MAIN));
            fillSentence.setLineSpacing(dp(4), 1.3f);
            fillWidget.addView(fillSentence);
        }

        View sp2 = new View(this);
        sp2.setLayoutParams(new LinearLayout.LayoutParams(1, dp(20)));
        fillWidget.addView(sp2);

        LinearLayout inputRow = new LinearLayout(this);
        inputRow.setOrientation(LinearLayout.HORIZONTAL);
        inputRow.setGravity(Gravity.CENTER_VERTICAL);
        GradientDrawable inputBg = new GradientDrawable();
        inputBg.setCornerRadius(dp(12));
        inputBg.setColor(Color.parseColor(SURFACE));
        inputBg.setStroke(dp(1), Color.parseColor(BORDER));
        inputRow.setBackground(inputBg);
        inputRow.setPadding(dp(4), dp(4), dp(4), dp(4));

        fillInput = new EditText(this);
        fillInput.setHint("输入单词...");
        fillInput.setSingleLine(true);
        fillInput.setBackgroundColor(Color.TRANSPARENT);
        fillInput.setPadding(dp(12), dp(10), dp(4), dp(10));
        fillInput.setTextSize(18);
        fillInput.setInputType(InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        LinearLayout.LayoutParams inputLp = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1);
        fillInput.setLayoutParams(inputLp);
        inputRow.addView(fillInput);

        fillCheckBtn = new Button(this);
        fillCheckBtn.setText("检查");
        fillCheckBtn.setAllCaps(false);
        fillCheckBtn.setTextColor(Color.WHITE);
        fillCheckBtn.setTextSize(14);
        fillCheckBtn.setTypeface(null, android.graphics.Typeface.BOLD);
        GradientDrawable checkBg = new GradientDrawable();
        checkBg.setCornerRadius(dp(10));
        checkBg.setColor(Color.parseColor(PRIMARY));
        fillCheckBtn.setBackground(checkBg);
        fillCheckBtn.setPadding(dp(18), 0, dp(18), 0);
        fillCheckBtn.setLayoutParams(new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(40)));
        fillCheckBtn.setOnClickListener(v -> checkFillAnswer());
        inputRow.addView(fillCheckBtn);

        fillWidget.addView(inputRow);

        fillResultLabel = new TextView(this);
        fillResultLabel.setTextSize(15);
        fillResultLabel.setGravity(Gravity.CENTER);
        fillResultLabel.setPadding(0, dp(14), 0, 0);
        fillResultLabel.setVisibility(View.GONE);
        fillWidget.addView(fillResultLabel);

        if (currentReviewIsFill) {
            normalWidget.setVisibility(View.GONE);
            fillWidget.setVisibility(View.VISIBLE);
        }

        View spacer6 = new View(this);
        spacer6.setLayoutParams(new LinearLayout.LayoutParams(1, dp(16)));
        box.addView(spacer6);

        box.addView(ghostButtonSmall("结束复习", v -> showHome()));
    }

    private void checkFillAnswer() {
        if (currentReviewWord == null || fillInput == null) return;
        String answer = fillInput.getText().toString().trim();
        boolean correct = answer.equalsIgnoreCase(currentReviewWord.word);

        fillInput.setEnabled(false);
        fillCheckBtn.setEnabled(false);
        fillResultLabel.setVisibility(View.VISIBLE);

        if (correct) {
            fillResultLabel.setText("✔ 正确! " + currentReviewWord.word);
            fillResultLabel.setTextColor(Color.parseColor("#059669"));
            new android.os.Handler().postDelayed(() -> review(currentReviewWord.id, "remembered"), 800);
        } else {
            fillResultLabel.setText("✘ 答案是: " + currentReviewWord.word);
            fillResultLabel.setTextColor(Color.parseColor("#DC2626"));
            fillWidget.addView(reviewButton("我写对了(算记住)", "#059669", v -> review(currentReviewWord.id, "remembered")));
            fillWidget.addView(reviewButton("没想起来", "#94A3B8", v -> review(currentReviewWord.id, "forgotten")));
        }
    }

    private Button reviewButton(String text, String color, View.OnClickListener listener) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextColor(Color.parseColor(color));
        b.setTextSize(16);
        b.setTypeface(null, android.graphics.Typeface.BOLD);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(52));
        lp.setMargins(0, 0, 0, dp(8));
        b.setLayoutParams(lp);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(14));
        int colorInt = Color.parseColor(color);
        int r = Color.red(colorInt);
        int g = Color.green(colorInt);
        int b2 = Color.blue(colorInt);
        bg.setColor(Color.argb(20, r, g, b2));
        bg.setStroke(dp(1), Color.argb(60, r, g, b2));
        b.setBackground(bg);
        b.setOnClickListener(listener);
        return b;
    }

    private void review(int id, String result) {
        db.markReviewed(id, result);
        if (!reviewQueue.isEmpty()) reviewQueue.remove(0);
        tryUploadAfterChange();
        showNextReview();
    }

    // ========== MASTERED WORDS ==========

    private void showMastered() {
        backStack.push(this::showHome);
        root = pageBase("已掌握");

        java.util.List<Word> words = db.masteredWords();
        if (words.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText("还没有已掌握的单词");
            empty.setTextSize(15);
            empty.setTextColor(Color.parseColor(TEXT_SUB));
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, dp(48), 0, 0);
            root.addView(empty);
        }
        for (Word w : words) {
            final int wordId = w.id;
            root.addView(wordCard(w, this::showMastered));
        }
        root.addView(ghostButton("返回首页", v -> showHome()));
    }

private void showSettings() {
        backStack.push(this::showHome);
        root = pageBase("设置");

        root.addView(sectionHeader("LLM 配置"));
        EditText baseUrl = settingsInput("Base URL", false);
        baseUrl.setText(settings.llmBaseUrl());
        root.addView(baseUrl);

        EditText apiKey = settingsInput("API Key", true);
        apiKey.setText(settings.llmApiKey());
        root.addView(apiKey);

        EditText model = settingsInput("Model", false);
        model.setText(settings.llmModel());
        root.addView(model);

        View spacer7 = new View(this);
        spacer7.setLayoutParams(new LinearLayout.LayoutParams(1, dp(20)));
        root.addView(spacer7);

        root.addView(sectionHeader("COS 云同步"));
        EditText secretId = settingsInput("SecretId", false);
        secretId.setText(settings.cosSecretId());
        root.addView(secretId);

        EditText secretKey = settingsInput("SecretKey", true);
        secretKey.setText(settings.cosSecretKey());
        root.addView(secretKey);

        EditText bucket = settingsInput("Bucket", false);
        bucket.setText(settings.cosBucket());
        root.addView(bucket);

        EditText region = settingsInput("Region", false);
        region.setText(settings.cosRegion());
        root.addView(region);

        View spacer8 = new View(this);
        spacer8.setLayoutParams(new LinearLayout.LayoutParams(1, dp(24)));
        root.addView(spacer8);

        root.addView(primaryButton("保存设置", v -> {
            settings.save(
                    baseUrl.getText().toString(), apiKey.getText().toString(),
                    model.getText().toString(),
                    secretId.getText().toString(), secretKey.getText().toString(),
                    bucket.getText().toString(), region.getText().toString()
            );
            toast("设置已保存");
            showHome();
        }));
        root.addView(ghostButton("返回首页", v -> showHome()));
    }

    private EditText settingsInput(String hint, boolean password) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setSingleLine(true);
        e.setTextSize(15);
        e.setTextColor(Color.parseColor(TEXT_MAIN));
        e.setInputType(password
                ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                : InputType.TYPE_CLASS_TEXT);
        e.setPadding(dp(14), dp(14), dp(14), dp(14));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, 0, 0, dp(8));
        e.setLayoutParams(lp);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(10));
        bg.setColor(Color.parseColor(SURFACE));
        bg.setStroke(dp(1), Color.parseColor(BORDER));
        e.setBackground(bg);
        return e;
    }

    private TextView sectionHeader(String text) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(12);
        t.setTextColor(Color.parseColor(TEXT_LIGHT));
        t.setAllCaps(true);
        t.setPadding(0, 0, 0, dp(10));
        return t;
    }

    // ═══════════════════ SYNC ═══════════════════

    private void runSync() {
        runBusy("同步中...", () -> sync.forceSync(db, this), this::showHome);
    }

    private void tryUploadAfterChange() {
        if (!settings.hasCos()) return;
        io.submit(() -> {
            try {
                String msg = sync.sync(db, this);
                runOnUiThread(() -> toast("同步: " + msg));
            } catch (Exception e) {
                runOnUiThread(() -> toast("同步失败: " + (e.getMessage() != null ? e.getMessage() : "网络错误")));
            }
        });
    }

    // ═══════════════════ UI HELPERS ═══════════════════

    private LinearLayout pageBase(String title) {
        ScrollView scroll = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(48), dp(24), dp(32));
        scroll.addView(box);
        setContentView(scroll);

        TextView h = new TextView(this);
        h.setText(title);
        h.setTextSize(26);
        h.setTextColor(Color.parseColor(TEXT_MAIN));
        h.setTypeface(null, android.graphics.Typeface.BOLD);
        h.setPadding(0, 0, 0, dp(20));
        box.addView(h);
        return box;
    }

    private Button primaryButton(String text, View.OnClickListener listener) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setTextSize(15);
        b.setTypeface(null, android.graphics.Typeface.BOLD);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(50));
        lp.setMargins(0, dp(4), 0, dp(4));
        b.setLayoutParams(lp);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(12));
        bg.setColor(Color.parseColor(PRIMARY));
        b.setBackground(bg);
        b.setOnClickListener(listener);
        return b;
    }

    private Button ghostButton(String text, View.OnClickListener listener) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextColor(Color.parseColor(TEXT_SUB));
        b.setTextSize(14);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(46));
        lp.setMargins(0, dp(2), 0, dp(2));
        b.setLayoutParams(lp);
        b.setBackgroundColor(Color.TRANSPARENT);
        b.setOnClickListener(listener);
        return b;
    }

    private Button ghostButtonSmall(String text, View.OnClickListener listener) {
        Button b = ghostButton(text, listener);
        b.setTextSize(13);
        b.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(40)));
        return b;
    }

    private Button dangerButton(String text, View.OnClickListener listener) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextColor(Color.parseColor("#DC2626"));
        b.setTextSize(14);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(46));
        lp.setMargins(0, dp(4), 0, dp(4));
        b.setLayoutParams(lp);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(12));
        bg.setColor(Color.parseColor("#FEF2F2"));
        bg.setStroke(dp(1), Color.parseColor("#FECACA"));
        b.setBackground(bg);
        b.setOnClickListener(listener);
        return b;
    }

    private TextView bodyText(String text, int sp, String color) {
        TextView tv = new TextView(this);
        tv.setText(text == null ? "" : text);
        tv.setTextSize(sp);
        tv.setTextColor(Color.parseColor(color));
        tv.setLineSpacing(dp(2), 1.2f);
        tv.setPadding(0, dp(4), 0, dp(4));
        return tv;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    // ═══════════════════ MISC ═══════════════════

    private interface Task { String run() throws Exception; }

    private void runBusy(String busy, Task task, Runnable afterOk) {
        toast(busy);
        io.submit(() -> {
            try {
                String msg = task.run();
                runOnUiThread(() -> { toast(msg); afterOk.run(); });
            } catch (Exception e) {
                runOnUiThread(() -> toast(e.getMessage() == null ? "操作失败" : e.getMessage()));
            }
        });
    }

    private void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show();
    }

    private void hideKeyboard(View view) {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(view.getWindowToken(), 0);
    }
}
