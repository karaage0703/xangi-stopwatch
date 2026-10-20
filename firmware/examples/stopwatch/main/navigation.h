#pragma once
#include <cstdlib>
// Return 1 for a horizontal page change, 2 for an item-page change.
inline int navigateDashboard(int dx, int dy, int& view, int& page, int pages) {
  if (std::abs(dx) >= 60 && std::abs(dx) > std::abs(dy) * 3 / 2) {
    view = (view + (dx < 0 ? 1 : 2)) % 3; page = 0; return 1;
  }
  if (view && std::abs(dy) >= 60 && std::abs(dy) > std::abs(dx) * 3 / 2) {
    page = (page + (dy < 0 ? 1 : pages - 1)) % pages; return 2;
  }
  return 0;
}
