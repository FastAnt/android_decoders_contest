import 'package:flutter/material.dart';

import 'screens/demo_screen.dart';

void main() {
  runApp(const ClientAndroidApp());
}

class ClientAndroidApp extends StatefulWidget {
  const ClientAndroidApp({super.key});

  @override
  State<ClientAndroidApp> createState() => _ClientAndroidAppState();
}

class _ClientAndroidAppState extends State<ClientAndroidApp> {
  ThemeMode _themeMode = ThemeMode.light;

  void _toggleThemeMode() {
    setState(() {
      _themeMode = _themeMode == ThemeMode.dark
          ? ThemeMode.light
          : ThemeMode.dark;
    });
  }

  ThemeData _buildTheme({required Brightness brightness}) {
    final isDay = brightness == Brightness.light;
    final fg = isDay ? Colors.black : Colors.white;
    final bg = isDay ? Colors.white : Colors.black;

    return ThemeData(
      brightness: brightness,
      scaffoldBackgroundColor: bg,
      colorScheme: ColorScheme.fromSeed(
        seedColor: fg,
        brightness: brightness,
        primary: fg,
        secondary: fg,
        surface: bg,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: bg,
        foregroundColor: fg,
        elevation: 0,
      ),
      textTheme: TextTheme(
        bodyLarge: TextStyle(color: fg),
        bodyMedium: TextStyle(color: fg),
        titleLarge: TextStyle(color: fg),
        titleMedium: TextStyle(color: fg),
        labelLarge: TextStyle(color: fg),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Neural Codec Startup Demo',
      themeMode: _themeMode,
      theme: _buildTheme(brightness: Brightness.light),
      darkTheme: _buildTheme(brightness: Brightness.dark),
      home: DemoScreen(
        onToggleTheme: _toggleThemeMode,
        isDayStyle: _themeMode == ThemeMode.light,
      ),
    );
  }
}
