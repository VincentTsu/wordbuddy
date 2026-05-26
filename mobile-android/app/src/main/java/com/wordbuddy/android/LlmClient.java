package com.wordbuddy.android;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class LlmClient {
    private final SettingsStore settings;

    LlmClient(SettingsStore settings) {
        this.settings = settings;
    }

    JSONObject queryWord(String word) throws Exception {
        if (!settings.hasLlm()) {
            throw new IllegalStateException("请先配置 LLM");
        }
        String prompt = "You are a concise English dictionary. For the word/phrase \""
                + word + "\", return ONLY this JSON (no markdown): "
                + "{\"word\":\"" + word + "\",\"phonetic\":\"IPA\",\"part_of_speech\":\"pos\","
                + "\"definition\":\"中文释义（简洁）\",\"english_definition\":\"brief English def\","
                + "\"examples\":[\"example 1\",\"example 2\"],\"synonyms\":[\"syn1\",\"syn2\"],\"notes\":\"\"}";

        JSONObject body = new JSONObject();
        body.put("model", settings.llmModel());
        JSONArray messages = new JSONArray();
        messages.put(new JSONObject().put("role", "user").put("content", prompt));
        body.put("messages", messages);
        body.put("temperature", 0.2);

        String base = settings.llmBaseUrl();
        String api = base.endsWith("/") ? base + "chat/completions" : base + "/chat/completions";
        HttpURLConnection conn = (HttpURLConnection) new URL(api).openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(20000);
        conn.setReadTimeout(45000);
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        conn.setRequestProperty("Authorization", "Bearer " + settings.llmApiKey());
        conn.setDoOutput(true);
        try (OutputStream out = conn.getOutputStream()) {
            out.write(body.toString().getBytes(StandardCharsets.UTF_8));
        }

        int code = conn.getResponseCode();
        String text = readAll(code >= 400 ? conn.getErrorStream() : conn.getInputStream());
        if (code >= 400) {
            throw new IllegalStateException("LLM 请求失败: " + code + " " + text);
        }
        JSONObject resp = new JSONObject(text);
        String content = resp.getJSONArray("choices")
                .getJSONObject(0)
                .getJSONObject("message")
                .getString("content")
                .trim();
        return new JSONObject(stripJsonFence(content));
    }

    private static String stripJsonFence(String text) {
        String t = text.trim();
        if (t.startsWith("```")) {
            int firstNl = t.indexOf('\n');
            int lastFence = t.lastIndexOf("```");
            if (firstNl >= 0 && lastFence > firstNl) {
                t = t.substring(firstNl + 1, lastFence).trim();
            }
        }
        return t;
    }

    private static String readAll(InputStream in) throws Exception {
        if (in == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        try (BufferedReader br = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = br.readLine()) != null) {
                sb.append(line);
            }
        }
        return sb.toString();
    }
}
