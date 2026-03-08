// LeakTracker - Main JS

document.addEventListener('DOMContentLoaded', () => {

    // Sidebar Toggle
    const toggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const closeBtn = document.getElementById('sidebarClose');

    function openSidebar() {
        sidebar?.classList.add('open');
        overlay?.classList.add('show');
    }

    function closeSidebar() {
        sidebar?.classList.remove('open');
        overlay?.classList.remove('show');
    }

    toggle?.addEventListener('click', openSidebar);
    overlay?.addEventListener('click', closeSidebar);
    closeBtn?.addEventListener('click', closeSidebar);

    // Auto-dismiss alerts
    document.querySelectorAll('.alert-custom').forEach(alert => {
        setTimeout(() => {
            alert.style.opacity = '0';
            alert.style.transition = 'opacity 0.4s';
            setTimeout(() => alert.remove(), 400);
        }, 4000);
    });

    // Animate stat values on page load
    document.querySelectorAll('.stat-value[data-value]').forEach(el => {
        const target = parseFloat(el.dataset.value);
        const prefix = el.dataset.prefix || '';
        const isInt = Number.isInteger(target);
        let start = 0;
        const duration = 800;
        const step = timestamp => {
            if (!start) start = timestamp;
            const progress = Math.min((timestamp - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            const current = eased * target;
            el.textContent = prefix + (isInt ? Math.round(current) : current.toFixed(1));
            if (progress < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    });

    // Month filter
    document.getElementById('monthFilter')?.addEventListener('change', function () {
        const url = new URL(window.location.href);
        url.searchParams.set('month', this.value);
        window.location.href = url.toString();
    });

});
