import customtkinter as ctk
from utils import round_height_cm
from constants import (
    COLOR_NOT_LOADED,
    COLOR_SUCCESS,
    COLOR_SUCCESS_HOVER,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_DANGER,
    COLOR_DANGER_HOVER,
    MIN_HEIGHT_CM,
    MAX_HEIGHT_CM,
    DEFAULT_HEIGHT_CM
)


def create_ui(root, app):
    """Create the main UI."""
    # Main container
    main_frame = ctk.CTkFrame(root)
    main_frame.pack(fill="both", expand=True, padx=10, pady=10)
    
    # OSC settings frame
    osc_settings_frame = ctk.CTkFrame(main_frame)
    osc_settings_frame.pack(fill="x", pady=(0, 10))
    
    osc_label = ctk.CTkLabel(osc_settings_frame, text="OSC Settings", font=ctk.CTkFont(weight="bold"))
    osc_label.pack(anchor="w", padx=10, pady=(10, 5))
    
    osc_container = ctk.CTkFrame(osc_settings_frame)
    osc_container.pack(fill="x", padx=10, pady=(5, 10))
    
    # Row 1: Local OSC Port (dynamic from oscquery server)
    ctk.CTkLabel(osc_container, text="Local OSC:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=5, pady=5)
    local_port_label = ctk.CTkLabel(osc_container, textvariable=app.osc_port, width=80, text_color="#218838")
    local_port_label.grid(row=0, column=1, sticky="w", padx=5, pady=5)
    
    # VRChat Port (aligned with Local OSC Port on same row)
    ctk.CTkLabel(osc_container, text="VRChat Port:").grid(row=0, column=2, sticky="w", padx=10, pady=5)
    port_label = ctk.CTkLabel(osc_container, textvariable=app.vrchat_port, width=80)
    port_label.grid(row=0, column=3, sticky="w", padx=5, pady=5)

    # Row 2: VRChat IP (editable) with Apply button
    ctk.CTkLabel(osc_container, text="VRChat IP:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
    app.ip_entry = ctk.CTkEntry(
        osc_container,
        textvariable=app.osc_ip,
        width=120
    )
    app.ip_entry.grid(row=1, column=1, sticky="w", padx=5, pady=5)

    # Apply button for IP changes
    apply_btn = ctk.CTkButton(
        osc_container,
        text="Apply",
        command=lambda: app.apply_ip_change(),
        width=60
    )
    apply_btn.grid(row=1, column=2, sticky="w", padx=10, pady=5)
    
    # Height display section with adjustment buttons on sides
    height_frame = ctk.CTkFrame(main_frame)
    height_frame.pack(fill="x", pady=(0, 10))
    
    height_label = ctk.CTkLabel(height_frame, text="Current Height", font=ctk.CTkFont(weight="bold"))
    height_label.pack(anchor="w", padx=10, pady=(10, 5))
    
    # Main height adjustment container with vertical layout
    height_main_frame = ctk.CTkFrame(height_frame)
    height_main_frame.pack(pady=5, fill="x")
    
    # Row 1: plus buttons
    plus_container = ctk.CTkFrame(height_main_frame)
    plus_container.pack(fill="x", pady=(0, 10))
    
    create_adjust_button(plus_container, "+1 cm", 1, app)
    create_adjust_button(plus_container, "+10 cm", 10, app)
    create_adjust_button(plus_container, "+100 cm", 100, app)
    
    # Row 2: height display
    app.height_display = ctk.CTkLabel(
        height_main_frame, 
        text="Not Loaded", 
        font=ctk.CTkFont(size=32, weight="bold"),
        text_color=COLOR_NOT_LOADED  # Orange color for "Not Loaded" state
    )
    app.height_display.pack(pady=(10, 5))
    
    # Row 3: minus buttons
    minus_container = ctk.CTkFrame(height_main_frame)
    minus_container.pack(fill="x", pady=(10, 5))
    
    create_adjust_button(minus_container, "-1 cm", -1, app)
    create_adjust_button(minus_container, "-10 cm", -10, app)
    create_adjust_button(minus_container, "-100 cm", -100, app)
    
    # Row 4: Slider with min/max input fields
    slider_frame = ctk.CTkFrame(height_main_frame)
    slider_frame.pack(fill="x", pady=5)
    
    # Min value entry (left side)
    min_entry_container = ctk.CTkFrame(slider_frame)
    min_entry_container.pack(side="left", padx=(0, 10))
    
    ctk.CTkLabel(min_entry_container, text="Min:", width=40).pack(side="left")
    app.slider_min_var = ctk.StringVar(value=str(app.slider_min_value))
    app.slider_min_var.trace_add("write", lambda *args: on_slider_range_change(app))
    app.slider_min_entry = ctk.CTkEntry(
        min_entry_container,
        textvariable=app.slider_min_var,
        width=60
    )
    app.slider_min_entry.pack(side="left", padx=(10, 10))
    
    # Slider (middle)
    app.height_slider = ctk.CTkSlider(
        slider_frame,
        from_=MIN_HEIGHT_CM,
        to=MAX_HEIGHT_CM,
        number_of_steps=10000,  # Allow smooth dragging for any cm value
        command=lambda val: on_slider_change(val, app)
    )
    app.height_slider.pack(side="left", fill="x", expand=True, padx=(0, 10))
    app.height_slider.set(DEFAULT_HEIGHT_CM)  # Initial slider position
    
    # Max value entry (right side)
    max_entry_container = ctk.CTkFrame(slider_frame)
    max_entry_container.pack(side="left")
    
    ctk.CTkLabel(max_entry_container, text="Max:", width=40).pack(side="left")
    app.slider_max_var = ctk.StringVar(value=str(app.slider_max_value))
    app.slider_max_var.trace_add("write", lambda *args: on_slider_range_change(app))
    app.slider_max_entry = ctk.CTkEntry(
        max_entry_container,
        textvariable=app.slider_max_var,
        width=60
    )
    app.slider_max_entry.pack(side="left", padx=(10, 10))
    
    # Profiles section
    profiles_frame = ctk.CTkFrame(main_frame)
    profiles_frame.pack(fill="both", expand=True, pady=(0, 10))
    
    profiles_label = ctk.CTkLabel(profiles_frame, text="Height Profiles", font=ctk.CTkFont(weight="bold"))
    profiles_label.pack(anchor="w", padx=10, pady=(10, 5))
    
    profiles_container = ctk.CTkFrame(profiles_frame)
    profiles_container.pack(fill="both", expand=True, padx=10, pady=(5, 10))
    
    # Create 4 profile rows
    app.profile_labels = {}
    app.profile_display_labels = {}
    
    for i in range(1, 5):
        row_frame = ctk.CTkFrame(profiles_container)
        row_frame.pack(fill="x", pady=5)
        
        # Profile label
        ctk.CTkLabel(row_frame, text=f"Profile {i}:", font=ctk.CTkFont(size=11)).pack(side="left", padx=10)
        
        # Height display for this profile
        height_var = ctk.StringVar(value="0 cm")
        display_label = ctk.CTkLabel(
            row_frame, 
            textvariable=height_var, 
            font=ctk.CTkFont(size=11),
            width=100,
            anchor="w"
        )
        display_label.pack(side="left", padx=10)
        app.profile_display_labels[i] = display_label
        app.profile_labels[i] = height_var
        
        # Save button
        save_btn = ctk.CTkButton(
            row_frame,
            text="Save",
            command=lambda num=i: app.save_profile(num),
            fg_color=COLOR_SUCCESS,
            hover_color=COLOR_SUCCESS_HOVER
        )
        save_btn.pack(side="left", padx=5)
        
        # Load button
        load_btn = ctk.CTkButton(
            row_frame,
            text="Load",
            command=lambda num=i: app.load_profile(num),
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER
        )
        load_btn.pack(side="left", padx=5)
    
    # Refresh profile display
    refresh_profile_display(app)
    
    # Preserve Height on Avatar Switch checkbox
    preserve_frame = ctk.CTkFrame(main_frame)
    preserve_frame.pack(fill="x", pady=(0, 10))
    
    app.preserve_height_var = ctk.BooleanVar(value=app.preserve_height_on_avatar)
    preserve_checkbox = ctk.CTkCheckBox(
        preserve_frame,
        text="Preserve Height on Avatar Switch",
        variable=app.preserve_height_var,
        command=lambda: save_preserve_flag(app),
        onvalue=True,
        offvalue=False
    )
    preserve_checkbox.pack(side="left", padx=10, pady=5)
    
    # Hide Console checkbox
    hide_console_frame = ctk.CTkFrame(main_frame)
    hide_console_frame.pack(fill="x", pady=(0, 10))
    
    app.hide_console_var = ctk.BooleanVar(value=app.hide_console if hasattr(app, 'hide_console') else False)
    hide_console_checkbox = ctk.CTkCheckBox(
        hide_console_frame,
        text="Hide Console Window",
        variable=app.hide_console_var,
        command=lambda: save_hide_console_flag(app),
        onvalue=True,
        offvalue=False
    )
    hide_console_checkbox.pack(side="left", padx=10, pady=5)
    
    # Startup Mode selection
    startup_frame = ctk.CTkFrame(main_frame)
    startup_frame.pack(fill="x", pady=(0, 10))
    
    ctk.CTkLabel(startup_frame, text="Startup Mode:", width=120).pack(side="left", padx=10, pady=5)
    
    app.startup_mode_var = ctk.StringVar(value=app.startup_mode)
    startup_menu = ctk.CTkOptionMenu(
        startup_frame,
        variable=app.startup_mode_var,
        values=["Query Current Height", "Load Fixed Height"],
        command=lambda mode: on_startup_mode_change(mode, app)
    )
    startup_menu.pack(side="left", padx=10, pady=5)
    
    # Fixed height entry (shown when Load Fixed Height is selected)
    app.fixed_height_var = ctk.StringVar(value=str(app.startup_height))
    app.fixed_height_entry = ctk.CTkEntry(
        startup_frame,
        textvariable=app.fixed_height_var,
        width=80
    )
    if app.startup_mode == "Load Fixed Height":
        app.fixed_height_entry.pack(side="left", padx=10, pady=5)
    
    # Add trace to update startup_height when user types in the field
    def on_fixed_height_change(*args):
        try:
            fixed_height = int(app.fixed_height_var.get())
            app.startup_height = fixed_height
        except (ValueError, TypeError):
            pass
    
    app.fixed_height_var.trace_add("write", on_fixed_height_change)
    
    # Quit button frame (bottom right)
    quit_frame = ctk.CTkFrame(main_frame)
    quit_frame.pack(fill="x", pady=(0, 10))
    
    quit_btn = ctk.CTkButton(
        quit_frame,
        text="Quit",
        command=app.on_closing,
        fg_color=COLOR_DANGER,
        hover_color=COLOR_DANGER_HOVER,
        width=100
    )
    quit_btn.pack(side="right", padx=10, pady=5)


def save_preserve_flag(app):
    """Save the preserve height on avatar switch setting."""
    new_value = app.preserve_height_var.get()
    # Update config via ConfigManager (thread-safe, saves to file)
    app.config_manager.update_config({"preserve_height_on_avatar_switch": new_value})
    # Update in-memory variable for immediate effect
    with app._height_lock:
        app.preserve_height_on_avatar = new_value


def save_hide_console_flag(app):
    """Save the hide console setting."""
    new_value = app.hide_console_var.get()
    # Call _toggle_console_visibility to show/hide console immediately
    app._toggle_console_visibility()


def on_startup_mode_change(mode, app):
    """Callback when startup mode changes."""
    if mode == "Load Fixed Height":
        app.fixed_height_entry.pack(side="left", padx=10, pady=5)
        # Save the fixed height value
        try:
            fixed_height = int(app.fixed_height_var.get())
            app.startup_height = fixed_height
        except (ValueError, TypeError):
            pass
    else:
        app.fixed_height_entry.pack_forget()
    
    # Update app variable and save config via ConfigManager (thread-safe)
    app.startup_mode = mode
    # Map UI display value to config value: "Load Fixed Height" -> "fixed_height", "Query Current Height" -> "query"
    config_mode_value = "fixed_height" if mode == "Load Fixed Height" else "query"
    app.config_manager.update_config({"startup_mode": config_mode_value})


def create_adjust_button(parent, text, value, app):
    """Create an adjustment button."""
    btn = ctk.CTkButton(
        parent,
        text=text,
        command=lambda v=value: app.adjust_height(v)
    )
    btn.pack(side="left", padx=(5, 5))


def refresh_profile_display(app):
    """Refresh the profile display labels."""
    for i in range(1, 5):
        profile_key = f"profile{i}"
        height = app.profiles.get(profile_key, 0)
        app.profile_labels[i].set(f"{height} cm")


def on_slider_range_change(app):
    """Callback when min/max slider range values change."""
    try:
        min_val = int(float(app.slider_min_var.get()))
        max_val = int(float(app.slider_max_var.get()))
        
        # Ensure min < max
        if min_val >= max_val:
            return
        
        # Update slider range
        app.height_slider.configure(from_=min_val, to=max_val)
        
    except (ValueError, TypeError):
        pass


def on_slider_change(value, app=None):
    """Callback when slider value changes."""
    if app is not None and hasattr(app, 'current_height'):
        try:
            min_val = int(float(app.slider_min_var.get()))
            max_val = int(float(app.slider_max_var.get()))
            value = max(min_val, min(max_val, float(value)))
        except (ValueError, TypeError):
            pass
        
        height = round_height_cm(value)
        
        # Update the current height display
        app.current_height.set(height)
        update_display(app)
        
        # Send to VRChat
        if hasattr(app, 'send_height'):
            app.send_height(height)


def update_display(app):
    """Update the height display."""
    if not app.height_loaded:
        app.height_display.configure(text="Not Loaded", text_color=COLOR_NOT_LOADED)
    else:
        height = app.current_height.get()
        app.height_display.configure(text=f"{height} cm", text_color="white")
