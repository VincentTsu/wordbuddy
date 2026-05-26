package com.wordbuddy.android;

import android.content.Context;
import android.content.SharedPreferences;

final class SettingsStore {
    private final SharedPreferences prefs;

    SettingsStore(Context context) {
        prefs = context.getSharedPreferences("word_buddy_settings", Context.MODE_PRIVATE);
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
