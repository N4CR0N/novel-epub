package io.github.n4cr0n.novelepub

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.chaquo.python.Python

/**
 * Python sunucusunu (arayüz + indirme/çeviri işleri) ayakta tutan hizmet.
 * Bildirim yalnız indirme/çeviri sürerken görünür: o sırada ön plan hizmetine geçer, ekran kapansa da çalışır
 * (uyanık kalma kilidi) ve bildirimde aşamayı gösterir. İş bitince bildirim kalkar (uygulama kapalıysa "hazır" notu
 * bırakılır). İş yokken ve uygulama kapalıyken 10 dakika sonra kendini kapatır.
 */
class WorkService : Service() {
    companion object {
        @Volatile var port: Int = 0
        @Volatile var token: String = ""
        @Volatile var error: String? = null
        @Volatile var activityVisible: Boolean = false
        private const val CHANNEL = "work"
        private const val NOTIF_ID = 1
        private const val IDLE_LIMIT_MS = 10 * 60 * 1000L

        @Volatile private var instance: WorkService? = null
        private const val DONE_ID = 2

        /** Uygulama ekrandayken çağrılır (arka plandan hizmet başlatmak Android'de yasak). */
        fun start(ctx: Context) {
            try {
                ctx.startService(Intent(ctx, WorkService::class.java))
            } catch (e: IllegalStateException) {
                // uygulama o an arka plandaysa: bir sonraki açılışta yeniden denenir
            }
        }

        /** Uygulama arka plana geçmeden hemen önce: iş sürüyorsa ön plan hizmetine şimdi geç (sonra izin verilmez). */
        fun syncNow() {
            instance?.sync()
        }
    }

    @Volatile private var running = false
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    @Volatile private var module: com.chaquo.python.PyObject? = null
    @Volatile private var foreground = false

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        createChannel()
        instance = this
        if (!running) {
            running = true
            Thread({ serve() }, "webnovel-hizmet").start()
        }
        return START_STICKY
    }

    private fun serve() {
        val module = try {
            val m = Python.getInstance().getModule("novel_epub.android_main")
            val p = m.callAttr("start", filesDir.absolutePath).toInt()  // önce sunucu (veri klasörü ayarlanır)
            token = m.callAttr("token").toString()
            port = p  // arayüz port görününce açılır: anahtar ondan önce hazır olmalı
            m
        } catch (e: Throwable) {
            error = e.toString()
            return
        }
        this.module = module
        var idleSince = 0L
        while (running) {
            try {
                Thread.sleep(if (foreground || activityVisible) 2000 else 4000)
                val busy = sync()
                if (busy || activityVisible) {
                    idleSince = 0L
                } else if (idleSince == 0L) {
                    idleSince = System.currentTimeMillis()
                } else if (System.currentTimeMillis() - idleSince > IDLE_LIMIT_MS) {
                    stopSelf()
                    return
                }
            } catch (e: InterruptedException) {
                return
            } catch (e: Throwable) {
                // durum okunamadıysa bir sonraki turda yeniden dene
            }
        }
    }

    /** İş sürüyor mu bak; sürüyorsa ilerleme bildirimiyle ön plana geç, bittiyse bildirimi kaldır. */
    @Synchronized
    fun sync(): Boolean {
        val m = module ?: return false
        val busy = try { m.callAttr("busy").toBoolean() } catch (e: Throwable) { return foreground }
        if (busy) {
            val status = try { m.callAttr("status").toString() } catch (e: Throwable) { "" }
            val text = status.ifEmpty { getString(R.string.notif_starting) }
            if (!foreground) {
                try {
                    val n = notification(text)
                    if (Build.VERSION.SDK_INT >= 34) {
                        startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
                    } else {
                        startForeground(NOTIF_ID, n)
                    }
                    foreground = true
                    lastText = text
                } catch (e: Exception) {
                    // Android arka planda ön plan hizmetine izin vermedi: iş yine sürer, bildirim gösterilemez
                }
            } else {
                update(text)
            }
        } else if (foreground) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            foreground = false
            lastText = ""
            if (!activityVisible) done()
        }
        holdWakeLock(busy)
        return busy
    }

    /** İş uygulama kapalıyken bittiyse kaydırılıp kapatılabilen tek bir "bitti" notu. */
    private fun done() {
        val open = PendingIntent.getActivity(
            this, 1, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val n = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.notif_done))
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        try {
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).notify(DONE_ID, n)
        } catch (e: SecurityException) {
            // bildirim izni yok
        }
    }

    private fun holdWakeLock(on: Boolean) {
        if (on && wakeLock?.isHeld != true) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "webnovel:is").apply {
                setReferenceCounted(false)
                acquire(6 * 60 * 60 * 1000L) // en çok 6 saat; iş sürerse bir sonraki turda yenilenir
            }
        } else if (!on && wakeLock?.isHeld == true) {
            wakeLock?.release()
        }
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val ch = NotificationChannel(CHANNEL, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW)
            ch.setShowBadge(false)
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
        }
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setContentIntent(open)
            .build()
    }

    private var lastText = ""
    private fun update(text: String) {
        if (text == lastText || !foreground) return
        lastText = text
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIF_ID, notification(text))
    }

    override fun onDestroy() {
        running = false
        instance = null
        if (wakeLock?.isHeld == true) wakeLock?.release()
        super.onDestroy()
    }
}
