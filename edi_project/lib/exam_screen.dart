import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:camera/camera.dart';
import 'api_service.dart';

class ExamScreen extends StatefulWidget {
  final String examTitle;
  const ExamScreen({super.key, required this.examTitle});

  @override
  State<ExamScreen> createState() => _ExamScreenState();
}

class _ExamScreenState extends State<ExamScreen> {
  CameraController? _controller;
  Timer? _captureTimer;
  final ApiService _apiService = ApiService();

  bool _isCameraReady   = false;
  String? _selectedOption;

  // ── AI warning state ──────────────────────────────────────
  bool   _isCheatingDetected = false;
  String _aiMessage          = "";

  // Prevent overlapping upload calls
  bool _isUploading = false;

  @override
  void initState() {
    super.initState();
    _initializeCamera();
  }

  // ── Camera initialisation ─────────────────────────────────
  Future<void> _initializeCamera() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) return;

      final front = cameras.firstWhere(
            (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );

      _controller = CameraController(
        front,
        ResolutionPreset.low,
        enableAudio: false,
      );

      await _controller!.initialize();
      if (!mounted) return;

      setState(() => _isCameraReady = true);
      _startProctoring();
    } catch (e) {
      debugPrint("Camera Init Error: $e");
    }
  }

  // ── Real-time AI proctoring ───────────────────────────────
  // CHANGED: removed mock; now calls real backend every 2 s.
  // Guard flag (_isUploading) ensures frames don't queue up if
  // the server is slow.
  void _startProctoring() {
    _captureTimer = Timer.periodic(const Duration(seconds: 2), (timer) async {
      // Skip if previous upload hasn't finished
      if (_isUploading) return;

      final ctrl = _controller;
      if (ctrl == null ||
          !ctrl.value.isInitialized ||
          ctrl.value.isTakingPicture) return;

      _isUploading = true;
      try {
        final XFile image = await ctrl.takePicture();

        // Send to backend → POST /proctor/upload-frame  (key: "file")
        final Map<String, dynamic> result =
        await _apiService.uploadFrame(File(image.path));

        // Clean up temp file after upload
        try {
          await File(image.path).delete();
        } catch (_) {}

        if (mounted) {
          setState(() {
            _isCheatingDetected = result['cheating'] as bool? ?? false;
            _aiMessage          = result['message']  as String? ?? "";
          });
        }
      } catch (e) {
        debugPrint("Proctoring error: $e");
        if (mounted) {
          setState(() {
            _isCheatingDetected = false;
            _aiMessage          = "Connection lost";
          });
        }
      } finally {
        _isUploading = false;
      }
    });
  }

  // ── Lifecycle ─────────────────────────────────────────────
  @override
  void dispose() {
    _captureTimer?.cancel();
    _controller?.dispose();
    super.dispose();
  }

  // ── Build ─────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.examTitle),
        automaticallyImplyLeading: false,
        actions: [_buildTimerBadge()],
      ),
      body: Stack(
        children: [
          // 1. Main exam content
          Padding(
            padding: const EdgeInsets.all(24.0),
            child: _buildQuestionUI(),
          ),

          // 2. Camera overlay (top-right)
          Positioned(
            top: 10,
            right: 10,
            child: _buildCameraContainer(),
          ),

          // 3. AI warning banner (top-centre) — only when cheating
          if (_isCheatingDetected)
            Positioned(
              top: 80,
              left: 20,
              right: 20,
              child: _buildWarningBanner(),
            ),
        ],
      ),
    );
  }

  // ── UI components (unchanged from original) ───────────────
  Widget _buildWarningBanner() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.red.withOpacity(0.9),
        borderRadius: BorderRadius.circular(8),
        boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 4)],
      ),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, color: Colors.white),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              "WARNING: $_aiMessage",
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCameraContainer() {
    return Container(
      width: 110,
      height: 150,
      decoration: BoxDecoration(
        color: Colors.black,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: _isCheatingDetected ? Colors.red : Colors.blue,
          width: 3,
        ),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: _isCameraReady
            ? CameraPreview(_controller!)
            : const Center(child: CircularProgressIndicator()),
      ),
    );
  }

  Widget _buildTimerBadge() {
    return Container(
      margin: const EdgeInsets.only(right: 130),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.red.shade50,
        borderRadius: BorderRadius.circular(20),
      ),
      child: const Text(
        "59:52",
        style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold),
      ),
    );
  }

  Widget _buildQuestionUI() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "Question 1 of 20",
          style: TextStyle(color: Colors.grey),
        ),
        const SizedBox(height: 10),
        const Text(
          "Which of the following is Supervised Learning?",
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 20),
        Expanded(
          child: ListView(
            children: ["K-Means", "Linear Regression", "PCA", "Association"]
                .map(
                  (opt) => RadioListTile<String>(
                title: Text(opt),
                value: opt,
                groupValue: _selectedOption,
                onChanged: (v) => setState(() => _selectedOption = v),
              ),
            )
                .toList(),
          ),
        ),
        SizedBox(
          width: double.infinity,
          height: 50,
          child: ElevatedButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("SUBMIT EXAM"),
          ),
        ),
      ],
    );
  }
}
