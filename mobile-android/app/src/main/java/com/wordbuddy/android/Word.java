package com.wordbuddy.android;

import org.json.JSONArray;

import java.util.ArrayList;
import java.util.List;

final class Word {
    int id;
    String word = "";
    String phonetic = "";
    String partOfSpeech = "";
    String definition = "";
    String englishDefinition = "";
    String examplesJson = "[]";
    String synonymsJson = "[]";
    String notes = "";
    int reviewStage;
    String nextReviewDate = "";
    int totalReviews;
    int correctReviews;
    String createdAt = "";
    String lastReviewedAt = "";
    boolean mastered;
    String updatedAt = "";
    String deletedAt = "";

    List<String> examples() {
        return parseArray(examplesJson);
    }

    private static List<String> parseArray(String text) {
        ArrayList<String> out = new ArrayList<>();
        try {
            JSONArray arr = new JSONArray(text == null || text.isEmpty() ? "[]" : text);
            for (int i = 0; i < arr.length(); i++) {
                out.add(arr.optString(i));
            }
        } catch (Exception ignored) {
        }
        return out;
    }
}
