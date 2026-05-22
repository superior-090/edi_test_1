import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';

class AiColors {
  static const bg0 = Color(0xFF05070D);
  static const bg1 = Color(0xFF090D18);
  static const panel = Color(0xB3121828);
  static const panelStrong = Color(0xE6111727);
  static const cyan = Color(0xFF72F7FF);
  static const blue = Color(0xFF5A7CFF);
  static const purple = Color(0xFFB15CFF);
  static const red = Color(0xFFFF4D6D);
  static const green = Color(0xFF42F59B);
  static const amber = Color(0xFFFFC857);
  static const border = Color(0x33FFFFFF);
}

class AiGradientBackground extends StatefulWidget {
  const AiGradientBackground({super.key, required this.child});

  final Widget child;

  @override
  State<AiGradientBackground> createState() => _AiGradientBackgroundState();
}

class _AiGradientBackgroundState extends State<AiGradientBackground>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 16),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: RadialGradient(
          center: Alignment.topRight,
          radius: 1.25,
          colors: [Color(0x332A66FF), AiColors.bg0],
        ),
      ),
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, child) => CustomPaint(
          painter: _ParticlePainter(_controller.value),
          child: child,
        ),
        child: widget.child,
      ),
    );
  }
}

class _ParticlePainter extends CustomPainter {
  _ParticlePainter(this.progress);

  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..style = PaintingStyle.fill;
    for (var i = 0; i < 42; i++) {
      final phase = (progress + i * 0.037) % 1;
      final x = (math.sin(i * 12.989) * 43758.5453).abs() % size.width;
      final y = ((math.cos(i * 78.233) * 24634.6345).abs() +
              phase * size.height * 0.18) %
          size.height;
      final opacity = 0.08 + (math.sin((phase + i) * math.pi * 2) + 1) * 0.04;
      paint.color = (i.isEven ? AiColors.cyan : AiColors.purple)
          .withValues(alpha: opacity);
      canvas.drawCircle(Offset(x, y), i % 5 == 0 ? 2.4 : 1.3, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _ParticlePainter oldDelegate) {
    return oldDelegate.progress != progress;
  }
}

class GlassCard extends StatelessWidget {
  const GlassCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.radius = 22,
    this.borderColor,
    this.margin,
    this.onTap,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final double radius;
  final Color? borderColor;
  final EdgeInsetsGeometry? margin;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final content = ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
        child: Container(
          margin: margin,
          padding: padding,
          decoration: BoxDecoration(
            color: AiColors.panel,
            borderRadius: BorderRadius.circular(radius),
            border: Border.all(color: borderColor ?? AiColors.border),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.35),
                blurRadius: 30,
                offset: const Offset(0, 18),
              ),
            ],
          ),
          child: child,
        ),
      ),
    );
    if (onTap == null) return content;
    return InkWell(borderRadius: BorderRadius.circular(radius), onTap: onTap, child: content);
  }
}

class GradientButton extends StatelessWidget {
  const GradientButton({
    super.key,
    required this.onPressed,
    required this.icon,
    required this.label,
    this.loading = false,
  });

  final VoidCallback? onPressed;
  final IconData icon;
  final String label;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: onPressed == null
            ? null
            : const LinearGradient(colors: [AiColors.cyan, AiColors.blue, AiColors.purple]),
        borderRadius: BorderRadius.circular(18),
        boxShadow: [
          BoxShadow(
            color: AiColors.cyan.withValues(alpha: onPressed == null ? 0 : 0.26),
            blurRadius: 22,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: FilledButton.icon(
        style: FilledButton.styleFrom(
          backgroundColor: Colors.transparent,
          disabledBackgroundColor: Colors.white10,
          foregroundColor: const Color(0xFF04111A),
          disabledForegroundColor: Colors.white38,
          shadowColor: Colors.transparent,
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 17),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        ),
        onPressed: onPressed,
        icon: loading
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : Icon(icon),
        label: Text(label, style: const TextStyle(fontWeight: FontWeight.w900)),
      ),
    );
  }
}

class StatusBadge extends StatelessWidget {
  const StatusBadge({
    super.key,
    required this.label,
    required this.color,
    this.icon,
    this.pulse = false,
  });

  final String label;
  final Color color;
  final IconData? icon;
  final bool pulse;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.36)),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (pulse) ...[
            PulseDot(color: color),
            const SizedBox(width: 7),
          ] else if (icon != null) ...[
            Icon(icon, color: color, size: 16),
            const SizedBox(width: 7),
          ],
          Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w800)),
        ],
      ),
    );
  }
}

class PulseDot extends StatefulWidget {
  const PulseDot({super.key, required this.color});

  final Color color;

  @override
  State<PulseDot> createState() => _PulseDotState();
}

class _PulseDotState extends State<PulseDot> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ScaleTransition(
      scale: Tween<double>(begin: 0.82, end: 1.16).animate(
        CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
      ),
      child: Container(
        width: 9,
        height: 9,
        decoration: BoxDecoration(
          color: widget.color,
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(color: widget.color.withValues(alpha: 0.7), blurRadius: 12),
          ],
        ),
      ),
    );
  }
}

class MetricTile extends StatelessWidget {
  const MetricTile({
    super.key,
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
    this.caption,
  });

  final IconData icon;
  final String label;
  final String value;
  final String? caption;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.all(16),
      borderColor: color.withValues(alpha: 0.26),
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [color.withValues(alpha: 0.9), color.withValues(alpha: 0.2)],
              ),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Icon(icon, color: Colors.white),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(value, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900)),
                const SizedBox(height: 2),
                Text(label, style: const TextStyle(color: Colors.white60, fontWeight: FontWeight.w600)),
                if (caption != null)
                  Text(caption!, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle({
    super.key,
    required this.title,
    required this.subtitle,
    this.action,
  });

  final String title;
  final String subtitle;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900)),
              const SizedBox(height: 4),
              Text(subtitle, style: const TextStyle(color: Colors.white60)),
            ],
          ),
        ),
        if (action != null) action!,
      ],
    );
  }
}

class MiniBars extends StatelessWidget {
  const MiniBars({super.key, required this.values, required this.color});

  final List<double> values;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        for (final value in values)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 2),
              child: FractionallySizedBox(
                heightFactor: value.clamp(0.08, 1),
                alignment: Alignment.bottomCenter,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.bottomCenter,
                      end: Alignment.topCenter,
                      colors: [color.withValues(alpha: 0.28), color],
                    ),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: const SizedBox(height: 90),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
