package com.wordbuddy.android;

import java.io.File;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

final class Utils {
    private Utils() {
    }

    static String today() {
        return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
    }

    static String nowIso() {
        return new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(new Date());
    }

    static String dateAfterDays(int days) {
        return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(
                new Date(System.currentTimeMillis() + days * 86400000L)
        );
    }

    static String sha1Hex(String text) throws Exception {
        return hex(MessageDigest.getInstance("SHA-1").digest(text.getBytes(StandardCharsets.UTF_8)));
    }

    static String md5Hex(File file) throws Exception {
        MessageDigest md = MessageDigest.getInstance("MD5");
        byte[] buf = new byte[65536];
        try (FileInputStream in = new FileInputStream(file)) {
            int n;
            while ((n = in.read(buf)) >= 0) {
                md.update(buf, 0, n);
            }
        }
        return hex(md.digest());
    }

    static byte[] hmacSha1(byte[] key, String text) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA1");
        mac.init(new SecretKeySpec(key, "HmacSHA1"));
        return mac.doFinal(text.getBytes(StandardCharsets.UTF_8));
    }

    static String hmacSha1Hex(byte[] key, String text) throws Exception {
        return hex(hmacSha1(key, text));
    }

    static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format(Locale.US, "%02x", b & 0xff));
        }
        return sb.toString();
    }
}
