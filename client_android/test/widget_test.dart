import 'package:flutter_test/flutter_test.dart';

import 'package:client_android/main.dart';
import 'package:client_android/screens/demo_screen.dart';

void main() {
  testWidgets('Demo screen renders', (WidgetTester tester) async {
    await tester.pumpWidget(const ClientAndroidApp());
    expect(find.byType(DemoScreen), findsOneWidget);
  });
}
