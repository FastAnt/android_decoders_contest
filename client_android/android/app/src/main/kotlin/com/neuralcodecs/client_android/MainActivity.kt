package com.neuralcodecs.client_android

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterActivity() {
    private var sageBridge: SageBridge? = null
    private var sameBridge: SameBridge? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val sage = SageBridge(this, flutterEngine.dartExecutor.binaryMessenger)
        sageBridge = sage
        sameBridge = SameBridge(
            this,
            flutterEngine.dartExecutor.binaryMessenger,
        ) { cores -> sage.applyAffinity(cores) }
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        sameBridge?.dispose()
        sameBridge = null
        sageBridge?.dispose()
        sageBridge = null
        super.cleanUpFlutterEngine(flutterEngine)
    }
}
