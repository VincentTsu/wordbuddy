package com.wordbuddy.android;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

final class CosSyncClient {
    private final SettingsStore settings;
    private final SharedPreferences meta;

    CosSyncClient(Context context, SettingsStore settings) {
        this.settings = settings;
        this.meta = context.getSharedPreferences("word_buddy_sync_meta", Context.MODE_PRIVATE);
    }

    String sync(WordDbHelper db, Context context) throws Exception {
        if (!settings.hasCos()) {
            throw new IllegalStateException("请先配置 COS");
        }
        File dbFile = db.dbFile(context);
        String remote = headEtag();
        if (!remote.isEmpty() && dbFile.exists()) {
            String local = Utils.md5Hex(dbFile);
            if (!local.equals(remote)) {
                File tmp = File.createTempFile("word_buddy_remote", ".db", context.getCacheDir());
                download(tmp);
                int merged = db.mergeFrom(tmp);
                tmp.delete();
                db.checkpoint();
                upload(dbFile);
                meta.edit().putString("last_uploaded_etag", Utils.md5Hex(dbFile)).apply();
                return "已合并云端词库：" + merged + " 条变更";
            }
        } else if (!remote.isEmpty()) {
            db.close();
            download(dbFile);
            meta.edit().putString("last_uploaded_etag", headEtag()).apply();
            return "已从云端下载词库";
        }

        db.checkpoint();
        String lastUploaded = meta.getString("last_uploaded_etag", "");
        if (dbFile.exists()) {
            String local = Utils.md5Hex(dbFile);
            if (!local.equals(lastUploaded)) {
                upload(dbFile);
                meta.edit().putString("last_uploaded_etag", Utils.md5Hex(dbFile)).apply();
                return "已上传本地改动";
            }
        }
        return "词库已是最新";
    }

    void download(File dest) throws Exception {
        HttpURLConnection conn = open("GET");
        int code = conn.getResponseCode();
        if (code >= 400) {
            throw new IllegalStateException("COS 下载失败: " + code);
        }
        File parent = dest.getParentFile();
        if (parent != null) {
            parent.mkdirs();
        }
        File tmp = new File(dest.getAbsolutePath() + ".download");
        try (InputStream in = conn.getInputStream(); OutputStream out = new FileOutputStream(tmp)) {
            copy(in, out);
        }
        if (tmp.length() < 100) {
            tmp.delete();
            throw new IllegalStateException("下载到的词库文件太小，已取消替换");
        }
        if (dest.exists()) {
            File bak = new File(dest.getAbsolutePath() + ".bak");
            copyFile(dest, bak);
        }
        if (!tmp.renameTo(dest)) {
            copyFile(tmp, dest);
            tmp.delete();
        }
    }

    void upload(File src) throws Exception {
        HttpURLConnection conn = open("PUT");
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/octet-stream");
        try (InputStream in = new FileInputStream(src); OutputStream out = conn.getOutputStream()) {
            copy(in, out);
        }
        int code = conn.getResponseCode();
        if (code >= 400) {
            throw new IllegalStateException("COS 上传失败: " + code);
        }
    }

    void uploadAndRemember(File src) throws Exception {
        upload(src);
        meta.edit().putString("last_uploaded_etag", Utils.md5Hex(src)).apply();
    }

    String headEtag() throws Exception {
        HttpURLConnection conn = open("HEAD");
        int code = conn.getResponseCode();
        if (code == 404) {
            return "";
        }
        if (code >= 400) {
            throw new IllegalStateException("COS 访问失败: " + code);
        }
        String etag = conn.getHeaderField("ETag");
        return etag == null ? "" : etag.replace("\"", "");
    }

    private HttpURLConnection open(String method) throws Exception {
        String host = settings.cosBucket() + ".cos." + settings.cosRegion() + ".myqcloud.com";
        String path = "/" + Constants.COS_OBJECT_KEY;
        URL url = new URL("https://" + host + path);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod(method);
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(45000);
        conn.setRequestProperty("Host", host);
        conn.setRequestProperty("Authorization", authorization(method.toLowerCase(Locale.US), path, host));
        return conn;
    }

    private String authorization(String method, String path, String host) throws Exception {
        long now = System.currentTimeMillis() / 1000L;
        String time = now + ";" + (now + 3600);
        String headerList = "host";
        String urlParamList = "";
        String httpString = method + "\n" + path + "\n\nhost=" + host + "\n";
        String stringToSign = "sha1\n" + time + "\n" + Utils.sha1Hex(httpString) + "\n";
        byte[] signKey = Utils.hmacSha1(settings.cosSecretKey().getBytes(StandardCharsets.UTF_8), time);
        String signature = Utils.hmacSha1Hex(signKey, stringToSign);
        return "q-sign-algorithm=sha1"
                + "&q-ak=" + settings.cosSecretId()
                + "&q-sign-time=" + time
                + "&q-key-time=" + time
                + "&q-header-list=" + headerList
                + "&q-url-param-list=" + urlParamList
                + "&q-signature=" + signature;
    }

    private static void copy(InputStream in, OutputStream out) throws Exception {
        byte[] buf = new byte[65536];
        int n;
        while ((n = in.read(buf)) >= 0) {
            out.write(buf, 0, n);
        }
    }

    private static void copyFile(File from, File to) throws Exception {
        try (InputStream in = new FileInputStream(from); OutputStream out = new FileOutputStream(to)) {
            copy(in, out);
        }
    }
}
