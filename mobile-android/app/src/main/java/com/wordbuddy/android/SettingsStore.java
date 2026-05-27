package com.wordbuddy.android;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;

final class SettingsStore {
    private final SharedPreferences prefs;

    SettingsStore(Context context) {
        prefs = context.getSharedPreferences("word_buddy_settings", Context.MODE_PRIVATE);
        loadDefaults(context);
    }

    private void loadDefaults(Context context) {
        try (InputStream in = context.getAssets().open("credentials.properties")) {
            Properties props = new Properties();
            props.load(in);
            SharedPreferences.Editor editor = null;
            for (String key : new String[]{
                    "llm_base_url", "llm_api_key", "llm_model",
                    "cos_secret_id", "cos_secret_key", "cos_bucket", "cos_region"
            }) {
                String val = props.getProperty(key);
                if (val != null && !val.isEmpty() && !prefs.contains(key)) {
                    if (editor == null) editor = prefs.edit();
                    editor.putString(key, val.trim());
                }
            }
            if (editor != null) editor.apply();
        } catch (IOException e) {
            // credentials.properties not found — user must configure manually
        }
    }

    String llmBaseUrl() {
        return prefs.getString("llm_base_url", "https://api.deepseek.com/v1");
    }

    String llmApiKey() {
        return prefs.getString("llm_api_key", "");
    }

    String llmModel() {
        return prefs.getString("llm_model", "deepseek-chat");
    }

    String cosSecretId() {
        return prefs.getString("cos_secret_id", "");
    }

    String cosSecretKey() {
        return prefs.getString("cos_secret_key", "");
    }

    String cosBucket() {
        return prefs.getString("cos_bucket", "");
    }

    String cosRegion() {
        return prefs.getString("cos_region", "ap-guangzhou");
    }

    int fillRatio() {
        return prefs.getInt("fill_ratio", 25);
    }

    boolean hasCos() {
        return !cosSecretId().isEmpty() && !cosSecretKey().isEmpty()
                && !cosBucket().isEmpty() && !cosRegion().isEmpty();
    }

    boolean hasLlm() {
        return !llmApiKey().isEmpty() && !llmBaseUrl().isEmpty() && !llmModel().isEmpty();
    }

    void save(String baseUrl, String apiKey, String model,
              String secretId, String secretKey, String bucket, String region) {
        prefs.edit()
                .putString("llm_base_url", baseUrl.trim())
                .putString("llm_api_key", apiKey.trim())
                .putString("llm_model", model.trim())
                .putString("cos_secret_id", secretId.trim())
                .putString("cos_secret_key", secretKey.trim())
                .putString("cos_bucket", bucket.trim())
                .putString("cos_region", region.trim())
                .apply();
    }
}
