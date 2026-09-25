/** Анимации при прокрутке: выбор механизма.
 *
 *  Основной путь — CSS scroll-timeline (`animation-timeline: view()`), он
 *  описан в index.css и работает без JavaScript. Но его поддерживают не все
 *  мобильные вебвью: на части телефонов эффекта просто не было. Там
 *  включается запасной путь — IntersectionObserver ставит класс `.is-in`,
 *  когда карточка въезжает в экран, а сама анимация остаётся CSS-переходом
 *  по transform/opacity. Позиция скролла в JS не читается. */

const SELECTOR = ".reveal";

export function installScrollMotion(): void {
  const root = document.documentElement;
  const native =
    typeof CSS !== "undefined" && CSS.supports?.("animation-timeline: view()");

  if (native) {
    root.classList.add("sda");
    return;
  }
  if (typeof IntersectionObserver === "undefined") return; // контент просто виден

  root.classList.add("js-reveal");

  const io = new IntersectionObserver(
    (entries) => {
      // Появившиеся одновременно карточки въезжают лесенкой, а не разом
      let order = 0;
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const el = entry.target as HTMLElement;
        el.style.transitionDelay = `${Math.min(order, 5) * 70}ms`;
        el.classList.add("is-in");
        order += 1;
        io.unobserve(el);
      }
    },
    { rootMargin: "0px 0px -6% 0px", threshold: 0.08 },
  );

  const watch = (node: ParentNode) => {
    node.querySelectorAll<HTMLElement>(`${SELECTOR}:not(.is-in)`).forEach((el) => io.observe(el));
  };

  watch(document);
  // Экраны монтируются динамически — новые карточки подхватываем по мере появления
  new MutationObserver((records) => {
    for (const r of records) {
      r.addedNodes.forEach((n) => {
        if (!(n instanceof HTMLElement)) return;
        if (n.matches(SELECTOR)) io.observe(n);
        watch(n);
      });
    }
  }).observe(document.body, { childList: true, subtree: true });
}
