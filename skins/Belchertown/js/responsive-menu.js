(function() {
    function onReady(callback) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", callback);
        } else {
            callback();
        }
    }

    function toggleDisplay(element) {
        var isOpen = element.style.display === "block";
        element.style.display = isOpen ? "" : "block";
        return !isOpen;
    }

    function directSubMenu(item) {
        for (var i = 0; i < item.children.length; i++) {
            if (item.children[i].classList && item.children[i].classList.contains("sub-menu")) {
                return item.children[i];
            }
        }
        return null;
    }

    function normalizeSubMenus(menu) {
        var containers = [menu].concat(Array.prototype.slice.call(menu.querySelectorAll(".sub-menu")));

        containers.forEach(function(container) {
            Array.prototype.slice.call(container.children).forEach(function(child) {
                if (!child.classList || !child.classList.contains("sub-menu")) {
                    return;
                }

                var previousItem = child.previousElementSibling;
                if (!previousItem || !previousItem.classList || !previousItem.classList.contains("menu-item")) {
                    return;
                }

                previousItem.appendChild(child);
                previousItem.classList.add("menu-item-has-children");
            });
        });

        menu.querySelectorAll(".menu-item > .sub-menu").forEach(function(submenu) {
            submenu.parentElement.classList.add("menu-item-has-children");
        });
    }

    onReady(function() {
        var menus = document.querySelectorAll("header .genesis-nav-menu, .nav-primary .genesis-nav-menu");

        menus.forEach(function(menu) {
            if (menu.dataset.responsiveMenuBound === "1") {
                return;
            }

            normalizeSubMenus(menu);

            menu.dataset.responsiveMenuBound = "1";
            menu.classList.add("responsive-menu");

            var icon = document.createElement("div");
            icon.className = "responsive-menu-icon";
            icon.setAttribute("role", "button");
            icon.setAttribute("tabindex", "0");
            icon.setAttribute("aria-label", "Menu");
            icon.setAttribute("aria-expanded", "false");
            menu.parentNode.insertBefore(icon, menu);

            function toggleMenu() {
                icon.setAttribute("aria-expanded", String(toggleDisplay(menu)));
            }

            icon.addEventListener("click", toggleMenu);
            icon.addEventListener("keydown", function(event) {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    toggleMenu();
                }
            });
        });

        window.addEventListener("resize", function() {
            if (window.innerWidth <= 768) {
                return;
            }

            document
                .querySelectorAll("header .genesis-nav-menu, .nav-primary .genesis-nav-menu, nav .sub-menu")
                .forEach(function(element) {
                    element.removeAttribute("style");
                });

            document.querySelectorAll(".responsive-menu .menu-item-has-children").forEach(function(item) {
                item.classList.remove("menu-open");
            });
        });

        document.addEventListener("click", function(event) {
            var item = event.target.closest(".responsive-menu .menu-item-has-children");
            if (!item || event.target !== item) {
                return;
            }
            if (window.innerWidth > 768) {
                return;
            }

            var submenu = directSubMenu(item);
            if (!submenu) {
                return;
            }

            var isOpen = toggleDisplay(submenu);
            item.classList.toggle("menu-open", isOpen);
        });
    });
})();
