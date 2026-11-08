// The header turns white once the page is scrolled past the top.
const syncHeader = () => document.body.classList.toggle('scrolled', scrollY > 40);
addEventListener('scroll', syncHeader, { passive: true });
syncHeader();
