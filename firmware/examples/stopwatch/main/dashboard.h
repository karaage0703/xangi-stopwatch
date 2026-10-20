// Included inside the firmware namespace, after canvas and Lock definitions.
struct DashboardRow {
  String name, detail, state;
  float used = 0, pace = -1;
  int reset = -1, seconds = -1;
  bool stale = false, active = false;
};
std::vector<DashboardRow> usageRows, workingRows;
int dashboardView = 0, dashboardPage = 0;
int usageTotal = 0, workingTotal = 0, runningTotal = 0;
bool multipleUsage = false, usageError = true, tasksError = true;
bool dashboardReceived = false;
String dashboardBackend;
uint32_t dashboardAt = 0, dashboardNextDraw = 0;
constexpr uint16_t DASH_BG = 0x0863, DASH_PANEL = 0x10E5, DASH_WATER = 0x0251;
constexpr uint16_t DASH_ACCENT = 0x5F7F, DASH_MUTED = 0xBDF7, DASH_GUIDE = 0xFFE0;
String jsonText(cJSON* object, const char* key) {
  cJSON* value = cJSON_GetObjectItemCaseSensitive(object, key);
  return cJSON_IsString(value) && value->valuestring ? String(value->valuestring) : String();
}
float jsonNumber(cJSON* object, const char* key, float fallback) {
  cJSON* value = cJSON_GetObjectItemCaseSensitive(object, key);
  return cJSON_IsNumber(value) && std::isfinite(value->valuedouble) ? value->valuedouble : fallback;
}
bool jsonBool(cJSON* object, const char* key) { return cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(object, key)); }
std::vector<DashboardRow> parseDashboardRows(cJSON* root, const char* key) {
  std::vector<DashboardRow> rows;
  cJSON* item = nullptr;
  cJSON_ArrayForEach(item, cJSON_GetObjectItemCaseSensitive(root, key)) {
    if (rows.size() >= 60) break;
    DashboardRow row;
    row.name = jsonText(item, "name"); row.detail = jsonText(item, "detail"); row.state = jsonText(item, "state");
    row.used = constrain(jsonNumber(item, "used", 0), 0, 100);
    row.pace = constrain(jsonNumber(item, "pace", -1), -1, 100);
    row.reset = constrain(jsonNumber(item, "reset", -1), -1, 1000000);
    row.seconds = constrain(jsonNumber(item, "seconds", -1), -1, 100000000);
    row.stale = jsonBool(item, "stale"); row.active = jsonBool(item, "active");
    rows.push_back(row);
  }
  return rows;
}
bool acceptDashboard(const uint8_t* data, size_t size) {
  cJSON* root = cJSON_ParseWithLength(reinterpret_cast<const char*>(data), size);
  if (!cJSON_IsObject(root) || !cJSON_IsArray(cJSON_GetObjectItemCaseSensitive(root, "usage")) ||
      !cJSON_IsArray(cJSON_GetObjectItemCaseSensitive(root, "working"))) { cJSON_Delete(root); return false; }
  auto usage = parseDashboardRows(root, "usage"), working = parseDashboardRows(root, "working");
  Lock lock;
  usageRows.swap(usage); workingRows.swap(working);
  multipleUsage = jsonBool(root, "multiple"); usageError = jsonBool(root, "usageError"); tasksError = jsonBool(root, "tasksError");
  dashboardBackend = jsonText(root, "backend");
  usageTotal = jsonNumber(root, "usageTotal", usageRows.size());
  workingTotal = jsonNumber(root, "workingTotal", workingRows.size());
  runningTotal = jsonNumber(root, "runningTotal", 0);
  dashboardAt = millis(); dashboardNextDraw = 0; dashboardReceived = true;
  cJSON_Delete(root); return true;
}
int dashboardPages() {
  size_t count = dashboardView == 1 ? usageRows.size() : workingRows.size();
  int perPage = dashboardView == 1 && !multipleUsage ? 1 : 3;
  return std::max(1, int((count + perPage - 1) / perPage));
}
String dashboardFit(String value, int width) {
  if (canvas.textWidth(value) <= width) return value;
  while (value.length() && canvas.textWidth(value + "…") > width) {
    int end = value.length() - 1;
    while (end > 0 && (uint8_t(value[end]) & 0xc0) == 0x80) --end;
    value.remove(end);
  }
  return value + "…";
}
void dashboardText(String value, int x, int y, int width, uint16_t color = TFT_WHITE) {
  canvas.setTextColor(color); canvas.drawString(dashboardFit(value, width), x, y);
}
String resetLabel(int minutes) {
  if (minutes < 0) return "リセット時刻 未取得";
  if (!minutes) return "リセット更新待ち";
  if (minutes >= 1440) return "リセットまで " + String(minutes / 1440) + "日 " + String(minutes % 1440 / 60) + "時間";
  return "リセットまで " + String(minutes / 60) + "時間 " + String(minutes % 60) + "分";
}
void drawDashboard() {
  if (!dashboardView || !canvasReady) return;
  bool stale = !dashboardReceived || uint32_t(millis() - dashboardAt) > 20000;
  bool failed = dashboardView == 1 ? usageError : tasksError;
  int pages = dashboardPages(); dashboardPage = dashboardPage % pages;
  canvas.fillScreen(DASH_BG);
  canvas.setTextDatum(middle_center);
  canvas.setFont(&fonts::lgfxJapanGothic_24);
  const char* title = dashboardView == 1 ? "AI利用量" : "タスク";
  bool water = dashboardView == 1 && !multipleUsage && !usageRows.empty();
  if (water) {
    auto& row = usageRows[dashboardPage];
    float surface = 466 * (1 - row.used / 100);
    for (int x = 0; x < 466; ++x) {
      int y = row.used <= 0 ? 466 : row.used >= 100 ? 0 : constrain(int(surface + 4 * sinf(x / 34.0f + millis() / 900.0f)), 0, 466);
      canvas.drawFastVLine(x, y, 466 - y, DASH_WATER);
    }
    if (row.pace >= 0) {
      int y = constrain(int(466 * (1 - row.pace / 100)), 1, 464);
      for (int x = 0; x < 466; x += 18) canvas.fillRect(x, y, 10, 2, DASH_GUIDE);
    }
    // Keep the water surface visible across the entire circular display.
    canvas.setFont(&fonts::lgfxJapanGothic_24);
    dashboardText(row.name, 233, 156, 310, DASH_ACCENT);
    canvas.setFont(&fonts::lgfxJapanGothic_20);
    dashboardText(row.detail, 233, 185, 310, DASH_MUTED);
    canvas.setFont(&fonts::lgfxJapanGothic_40);
    dashboardText("使用 " + String(int(roundf(row.used))) + "%", 233, 236, 310);
    canvas.setFont(&fonts::lgfxJapanGothic_20);
    dashboardText(row.pace < 0 ? "目安 未取得" : "目安 " + String(int(roundf(row.pace))) + "%", 233, 284, 310, DASH_GUIDE);
    dashboardText(resetLabel(row.reset), 233, 315, 310, DASH_MUTED);
    failed = failed || row.stale;
  } else {
    auto& rows = dashboardView == 1 ? usageRows : workingRows;
    if (rows.empty()) {
      canvas.setFont(&fonts::lgfxJapanGothic_24);
      dashboardText(stale || failed ? "情報を取得できません" : dashboardView == 1 ? "利用量 未取得" : "該当するタスクはありません", 233, 220, 390);
    }
    for (int i = 0; i < 3 && dashboardPage * 3 + i < int(rows.size()); ++i) {
      auto& row = rows[dashboardPage * 3 + i];
      int y = 135 + i * 87;
      canvas.fillRoundRect(55, y - 12, 356, 81, 12, DASH_PANEL);
      canvas.setTextDatum(top_left); canvas.setFont(&fonts::lgfxJapanGothic_20);
      dashboardText(row.name, 69, y - 6, 326);
      canvas.setFont(&fonts::lgfxJapanGothic_16);
      if (dashboardView == 1) {
        dashboardText(row.detail, 69, y + 17, 205, DASH_MUTED);
        canvas.setTextDatum(top_right);
        dashboardText(String(int(roundf(row.used))) + "% / " + (row.pace < 0 ? String("未取得") : String(int(roundf(row.pace))) + "%"), 397, y + 17, 125, DASH_GUIDE);
        canvas.fillRoundRect(69, y + 44, 328, 12, 5, DASH_BG);
        if (row.used > 0) canvas.fillRoundRect(69, y + 44, std::max(1, int(328 * row.used / 100)), 12, 5, DASH_ACCENT);
        if (row.pace >= 0) canvas.fillRect(69 + std::min(326, int(328 * row.pace / 100)), y + 41, 2, 18, DASH_GUIDE);
        failed = failed || row.stale;
      } else {
        dashboardText(row.detail, 69, y + 18, 326, DASH_MUTED);
        String status = row.state;
        if (row.seconds >= 0) {
          int seconds = row.seconds + (stale || failed ? 0 : (millis() - dashboardAt) / 1000);
          status += "  " + String(seconds / 60) + "分" + String(seconds % 60) + "秒";
        }
        dashboardText(status, 69, y + 43, 326, row.active ? DASH_ACCENT : DASH_MUTED);
        if (row.active && !stale && !failed) canvas.fillCircle(393, y + 50, 2 + (millis() / 500) % 2, DASH_ACCENT);
      }
      canvas.setTextDatum(middle_center);
    }
  }
  canvas.setTextDatum(middle_center); canvas.setFont(&fonts::lgfxJapanGothic_24);
  dashboardText(title, 233, 65, 260);
  canvas.setFont(&fonts::lgfxJapanGothic_16);
  String sub = stale ? "接続待ち・前回値" : failed ? "更新待ち・前回値" : dashboardView == 1 ? (multipleUsage ? "使用率 / 目安" : dashboardBackend) : "";
  if (dashboardView >= 2 && !stale && !failed) sub = "実行中 " + String(runningTotal) + " / 全 " + String(workingTotal) + "件";
  dashboardText(sub, 233, 96, 290, stale || failed ? DASH_GUIDE : DASH_MUTED);
  int total = dashboardView == 1 ? usageTotal : workingTotal;
  String footer = String(dashboardPage + 1) + "/" + String(pages) + (pages > 1 ? "  上下で送る" : "");
  int shown = dashboardView == 1 ? usageRows.size() : workingRows.size();
  if (total > shown) footer += " (先頭" + String(shown) + "件)";
  dashboardText(footer, 233, 410, 270, DASH_MUTED);
  for (int i = 0; i < 3; ++i) canvas.fillCircle(213 + i * 20, 439, i == dashboardView ? 4 : 2, i == dashboardView ? DASH_ACCENT : DASH_MUTED);
  canvas.pushSprite(0, 0);
}
