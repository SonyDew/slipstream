;(function () {
  try {
    var stored = window.localStorage.getItem('slipstream-theme')
    var dark =
      stored === 'dark' ||
      ((stored === 'system' || !stored) &&
        window.matchMedia('(prefers-color-scheme: dark)').matches)

    if (dark) {
      document.documentElement.classList.add('dark')
      document.documentElement.style.colorScheme = 'dark'
      var meta = document.querySelector('meta[name="theme-color"]')
      if (meta) meta.setAttribute('content', '#11130e')
    }
  } catch (error) {
    /* Blocked site data: fall through to the light default. */
  }
})()
