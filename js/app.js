document.addEventListener("DOMContentLoaded", () => {
  // Mantiene el menú de cuenta sincronizado con la sesión del servidor.
  const accountActions = document.querySelector('.account-actions');
  if (accountActions) {
    fetch('/api/sesion').then(r => r.ok ? r.json() : null).then(state => {
      if (!state) return;
      if (state.admin) {
        accountActions.innerHTML = '<a class="login-link" href="/admin">Administración</a><a class="login-link" href="/admin/editor">Editar página</a><a class="login-link" href="/admin/usuarios">Usuarios</a><a class="button button-primary button-small" href="/salir">Cerrar sesión</a>';
      } else if (state.logged_in) {
        accountActions.innerHTML = '<a class="login-link" href="/cuenta">Mi cuenta</a><a class="button button-primary button-small" href="/salir">Cerrar sesión</a>';
      }
    }).catch(() => {});
  }

  const year = document.querySelector("#year");
  if (year) year.textContent = new Date().getFullYear();

  // Menú adaptable para teléfonos.
  const menuToggle = document.querySelector("#menuToggle");
  const mainNav = document.querySelector("#mainNav");

  if (menuToggle && mainNav) {
    menuToggle.addEventListener("click", () => {
      const opened = mainNav.classList.toggle("open");
      menuToggle.textContent = opened ? "✕" : "☰";
      menuToggle.setAttribute("aria-expanded", String(opened));
      menuToggle.setAttribute("aria-label", opened ? "Cerrar menú" : "Abrir menú");
    });

    mainNav.querySelectorAll("a").forEach(link => {
      link.addEventListener("click", () => {
        mainNav.classList.remove("open");
        menuToggle.textContent = "☰";
        menuToggle.setAttribute("aria-expanded", "false");
        menuToggle.setAttribute("aria-label", "Abrir menú");
      });
    });
  }

  // Carrusel de fotografías de la portada.
  const carousel = document.querySelector("#heroCarousel");
  const previousButton = document.querySelector("#prevSlide");
  const nextButton = document.querySelector("#nextSlide");
  const dotsContainer = document.querySelector("#carouselDots");
  const slideNumber = document.querySelector("#slideNumber");

  if (carousel && previousButton && nextButton && dotsContainer) {
    const slides = [...carousel.querySelectorAll(".carousel-slide")];
    const dots = [...dotsContainer.querySelectorAll(".carousel-dot")];
    let current = 0;
    let timer = null;

    function showSlide(index) {
      current = (index + slides.length) % slides.length;

      slides.forEach((slide, i) => {
        slide.classList.toggle("active", i === current);
        slide.setAttribute("aria-hidden", String(i !== current));
      });

      dots.forEach((dot, i) => {
        dot.classList.toggle("active", i === current);
        dot.setAttribute("aria-current", i === current ? "true" : "false");
      });

      if (slideNumber) {
        slideNumber.textContent = String(current + 1).padStart(2, "0");
      }
    }

    function stopTimer() {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    }

    function startTimer() {
      stopTimer();
      if (!document.hidden) {
        timer = setInterval(() => showSlide(current + 1), 5000);
      }
    }

    nextButton.addEventListener("click", () => {
      showSlide(current + 1);
      startTimer();
    });

    previousButton.addEventListener("click", () => {
      showSlide(current - 1);
      startTimer();
    });

    dots.forEach((dot, i) => {
      dot.addEventListener("click", () => {
        showSlide(i);
        startTimer();
      });
    });

    carousel.addEventListener("mouseenter", stopTimer);
    carousel.addEventListener("mouseleave", startTimer);

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopTimer();
      else startTimer();
    });

    showSlide(0);
    startTimer();
  }

  // Ocultar la etiqueta del video mientras se reproduce.
  const lakeVideo = document.querySelector("#lakeVideo");
  const videoCaption = document.querySelector(".video-caption");

  if (lakeVideo && videoCaption) {
    lakeVideo.addEventListener("play", () => videoCaption.style.opacity = "0");
    lakeVideo.addEventListener("pause", () => videoCaption.style.opacity = "1");
    lakeVideo.addEventListener("ended", () => videoCaption.style.opacity = "1");
  }
});
