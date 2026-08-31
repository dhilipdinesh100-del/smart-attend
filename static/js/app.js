// SmartAttend Core Interactive JavaScript Library

document.addEventListener('DOMContentLoaded', () => {
  initLiveClock();
  initMobileSidebar();
  initFormLoadingStates();
  initToastDismiss();
  initKeyboardModalCloser();
  setupGlobalFetchCsrf();
});

// Setup CSRF header on fetch calls
function setupGlobalFetchCsrf() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) return;
  const token = meta.getAttribute('content');

  const originalFetch = window.fetch;
  window.fetch = function (url, options = {}) {
    options = options || {};
    options.headers = options.headers || {};

    // If headers is Headers instance or object
    if (options.headers instanceof Headers) {
      if (!options.headers.has('X-CSRF-Token') && token) {
        options.headers.append('X-CSRF-Token', token);
      }
    } else if (typeof options.headers === 'object') {
      if (!options.headers['X-CSRF-Token'] && token) {
        options.headers['X-CSRF-Token'] = token;
      }
    }

    return originalFetch(url, options);
  };
}

// Real-Time Live Clock
function initLiveClock() {
  const clockEl = document.getElementById('live-clock-time');
  if (!clockEl) return;

  function update() {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true
    });
  }

  update();
  setInterval(update, 1000);
}

// Mobile Sidebar Drawer
function initMobileSidebar() {
  const toggleBtn = document.getElementById('mobileMenuBtn');
  const sidebar = document.querySelector('.sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  const navLinks = document.querySelectorAll('.nav-link');

  if (toggleBtn && sidebar && backdrop) {
    toggleBtn.addEventListener('click', () => {
      const isOpen = sidebar.classList.toggle('open');
      backdrop.classList.toggle('active', isOpen);
      toggleBtn.setAttribute('aria-expanded', String(isOpen));
    });

    backdrop.addEventListener('click', () => {
      sidebar.classList.remove('open');
      backdrop.classList.remove('active');
      toggleBtn.setAttribute('aria-expanded', 'false');
    });

    navLinks.forEach(link => {
      link.addEventListener('click', () => {
        if (window.innerWidth <= 860) {
          sidebar.classList.remove('open');
          backdrop.classList.remove('active');
          toggleBtn.setAttribute('aria-expanded', 'false');
        }
      });
    });

    window.addEventListener('resize', () => {
      if (window.innerWidth > 860) {
        sidebar.classList.remove('open');
        backdrop.classList.remove('active');
        toggleBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }
}

// Toast Notifications System
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${message}</span>
    <button class="toast-close-btn" onclick="this.parentElement.remove()" aria-label="Close">&times;</button>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function initToastDismiss() {
  document.querySelectorAll('.toast').forEach(toast => {
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 300);
    }, 4500);
  });
}

// Form Loading State & Double-submission Prevention
function initFormLoadingStates() {
  document.querySelectorAll('form[data-loading-text]').forEach(form => {
    form.addEventListener('submit', function (e) {
      const submitBtn = this.querySelector('button[type="submit"]');
      if (submitBtn && !submitBtn.disabled) {
        const loadingText = this.getAttribute('data-loading-text') || 'Processing...';
        submitBtn.disabled = true;
        submitBtn.classList.add('loading');
        submitBtn.innerHTML = `<span class="spinner"></span> <span>${loadingText}</span>`;
      }
    });
  });
}

// Modal Controllers
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove('active');
    document.body.style.overflow = '';
  }
}

function initKeyboardModalCloser() {
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-backdrop.active').forEach(m => {
        m.classList.remove('active');
      });
      document.body.style.overflow = '';
    }
  });

  document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-backdrop')) {
      e.target.classList.remove('active');
      document.body.style.overflow = '';
    }
  });
}
