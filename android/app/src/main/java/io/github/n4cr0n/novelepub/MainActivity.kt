package io.github.n4cr0n.novelepub

import android.Manifest
import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.addCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.chaquo.python.Python
import java.io.File
import java.net.URLDecoder
import java.net.URLEncoder

/** Arayüz: bilgisayardaki uygulamanın aynısı, telefondaki yerel Python sunucusundan (127.0.0.1) açılır. */
class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private val handler = Handler(Looper.getMainLooper())
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var sharedLink: String? = null
    private var loaded = false

    private val pickFile = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        fileCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
        fileCallback = null
    }
    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this)
        web = WebView(this)
        root.addView(web, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        setContentView(root)
        // Android 15 ekranı kenardan kenara çizer: durum çubuğu ve klavye için boşluk bırak
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val b = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.setPadding(b.left, b.top, b.right, b.bottom)
            insets
        }

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.allowFileAccess = false
        web.settings.setSupportMultipleWindows(false)
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (url.host == "127.0.0.1") return false
                // dış bağlantılar (ör. API anahtarı sayfası) telefonun tarayıcısında açılır
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, url))
                } catch (_: ActivityNotFoundException) {
                }
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                pickFile.launch(arrayOf("*/*"))
                return true
            }
        }
        web.setDownloadListener { url, _, _, _, _ -> saveBook(url) }

        onBackPressedDispatcher.addCallback(this) {
            if (web.canGoBack()) web.goBack() else finish()
        }

        if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        handleShare(intent)
        WorkService.start(this)
        waitForServer()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
        if (loaded) sharedLink?.let { link ->
            web.evaluateJavascript("window.useSharedLink && useSharedLink(${org.json.JSONObject.quote(link)})", null)
            sharedLink = null
        }
    }

    override fun onStart() {
        super.onStart()
        WorkService.activityVisible = true
        WorkService.start(this) // hizmet boşta kalıp kapandıysa yeniden aç
    }

    override fun onStop() {
        WorkService.activityVisible = false
        super.onStop()
    }

    /** Tarayıcıdan "Paylaş → WebNovel" ile gelen roman linki. */
    private fun handleShare(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND) return
        val text = intent.getStringExtra(Intent.EXTRA_TEXT) ?: return
        sharedLink = Regex("https?://\\S+").find(text)?.value
    }

    private fun waitForServer() {
        val port = WorkService.port
        val err = WorkService.error
        when {
            port > 0 -> {
                // erişim anahtarı adresin # kısmında: telefondaki başka uygulamalar sunucuyu kullanamaz
                val hash = "#t=" + WorkService.token + (sharedLink?.let { "&url=" + URLEncoder.encode(it, "UTF-8") } ?: "")
                sharedLink = null
                web.loadUrl("http://127.0.0.1:$port/$hash")
                loaded = true
            }
            err != null -> web.loadDataWithBaseURL(
                null, "<pre style='white-space:pre-wrap;padding:16px'>Python başlatılamadı:\n${err.replace("<", "&lt;")}</pre>",
                "text/html", "utf-8", null
            )
            else -> handler.postDelayed({ waitForServer() }, 150)
        }
    }

    /** "Hazır kitaplar"dan dokunulan kitabı İndirilenler/WebNovel klasörüne kaydeder ve okuma uygulamasıyla açar. */
    private fun saveBook(url: String) {
        if (!url.contains("/indir/")) return
        val name = URLDecoder.decode(url.substringAfter("/indir/").substringBefore("?"), "UTF-8")
        Thread {
            try {
                val path = Python.getInstance().getModule("novel_epub.android_main").callAttr("output_path", name).toString()
                val uri = copyToDownloads(File(path))
                runOnUiThread {
                    Toast.makeText(this, getString(R.string.saved_to_downloads, name), Toast.LENGTH_SHORT).show()
                    open(uri, mimeOf(name))
                }
            } catch (e: Throwable) {
                runOnUiThread { Toast.makeText(this, e.message ?: e.toString(), Toast.LENGTH_LONG).show() }
            }
        }.start()
    }

    private fun copyToDownloads(src: File): Uri {
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, src.name)
                put(MediaStore.Downloads.MIME_TYPE, mimeOf(src.name))
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/WebNovel")
            }
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("İndirilenler klasörüne yazılamadı")
            contentResolver.openOutputStream(uri)!!.use { out -> src.inputStream().use { it.copyTo(out) } }
            return uri
        }
        // Android 9 ve öncesi: izin istemeden uygulamanın kendi İndirilenler klasörü
        val dir = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "WebNovel").apply { mkdirs() }
        val dst = File(dir, src.name)
        src.copyTo(dst, overwrite = true)
        return FileProvider.getUriForFile(this, "$packageName.files", dst)
    }

    private fun open(uri: Uri, mime: String) {
        val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        try {
            startActivity(Intent.createChooser(view, null))
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, R.string.no_reader, Toast.LENGTH_LONG).show()
        }
    }

    private fun mimeOf(name: String): String = when (name.substringAfterLast('.').lowercase()) {
        "epub" -> "application/epub+zip"
        "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "html" -> "text/html"
        "md" -> "text/markdown"
        else -> "text/plain"
    }
}
