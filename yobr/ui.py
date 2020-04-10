# Copyright (c) 2020 Philippe Proulx <eepp.ca>
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import yobr
import yobr.br
import sys
import math
import os.path
import logging
import webbrowser
import functools
import datetime
import PyQt5 as qtwidgets
import PyQt5.QtWidgets as qtwidgets
import PyQt5.QtCore as qtcore
import PyQt5.QtGui as qtgui


# common fonts
_mono_font_family = 'DejaVu Sans Mono, Bitstream Vera Sans Mono, monospace'
_mono_font = qtgui.QFont(_mono_font_family, 10)
_mono_font_bold = qtgui.QFont(_mono_font_family, 10)
_mono_font_bold.setBold(True)


# a minimalist progress bar (two colors, thin border)
class _MinimalistProgressBar(qtwidgets.QProgressBar):
    def __init__(self):
        super().__init__()
        self.is_reversed = False

    # `True` if the foreground and background colors are reversed
    @property
    def is_reversed(self):
        return self._is_reversed

    @is_reversed.setter
    def is_reversed(self, is_reversed):
        fg_colour = 'rgba(0, 0, 0, .75)'
        bg_colour = 'rgba(255, 255, 255, .9)'

        if is_reversed:
            fg_colour, bg_colour = bg_colour, fg_colour

        stylesheet = '''
            QProgressBar:horizontal {{
                border: 1px solid {fg};
                border-radius: 0;
                padding: 0;
                background-color: {bg};
            }}

            QProgressBar::chunk:horizontal {{
                background: {fg};
            }}
        '''.format(fg=fg_colour, bg=bg_colour)
        self.setStyleSheet(stylesheet)


# build stage colours when used as background colours
_BUILD_STAGE_COLORS_BG = {
    yobr.br.PkgBuildStage.UNKNOWN: '#bdc3c7',
    yobr.br.PkgBuildStage.DOWNLOADED: '#b280c7',
    yobr.br.PkgBuildStage.EXTRACTED: '#8e44ad',
    yobr.br.PkgBuildStage.CONFIGURED: '#f1c40f',
    yobr.br.PkgBuildStage.PATCHED: '#e67e22',
    yobr.br.PkgBuildStage.BUILT: '#1abc9c',
    yobr.br.PkgBuildStage.INSTALLED: '#2ecc71',
}

# build stage colours when used as foreground colours (slightly darker)
_BUILD_STAGE_COLORS_FG = {
    yobr.br.PkgBuildStage.UNKNOWN: '#838e96',
    yobr.br.PkgBuildStage.DOWNLOADED: '#914dae',
    yobr.br.PkgBuildStage.EXTRACTED: '#8e44ad',
    yobr.br.PkgBuildStage.CONFIGURED: '#c29d0b',
    yobr.br.PkgBuildStage.PATCHED: '#a85913',
    yobr.br.PkgBuildStage.BUILT: '#148f77',
    yobr.br.PkgBuildStage.INSTALLED: '#17a351',
}


# package build state
class _PkgBuildState(qtwidgets.QWidget):
    def __init__(self, pkg_build, pkg_build_monitor):
        super().__init__()
        self._pkg_build = pkg_build
        self._pkg_build_monitor = pkg_build_monitor
        self._is_selected = False
        self._build_ui()
        self.update_from_state()

    # the monitored package build object
    @property
    def pkg_build(self):
        return self._pkg_build

    # `True` if this package build state is selected
    @property
    def is_selected(self):
        return self._is_selected

    @is_selected.setter
    def is_selected(self, is_selected):
        self._is_selected = is_selected

        # reverse the progress bar's colours as this widget's background
        # colour becomes black
        self._pbar.is_reversed = is_selected

        # update widget properties now that this is marked as selected
        self.update_from_state()

    def _build_ui(self):
        # background label (no text; just for the colour); assigning
        # this as its parent makes the label float under the other
        # widgets managed by this widget's layout
        self._bg_lbl = qtwidgets.QLabel('', self)
        self._bg_lbl.setSizePolicy(qtwidgets.QSizePolicy.Fixed,
                                   qtwidgets.QSizePolicy.Fixed)

        # horizontal box for name label and progress bar
        hbox = qtwidgets.QHBoxLayout()
        hbox.setSpacing(0)
        hbox.setContentsMargins(0, 0, 0, 0)

        # left padding
        hbox.addSpacing(5)

        # name label
        self._name_lbl = qtwidgets.QLabel(self._pkg_build.info.name)
        self._name_lbl.setFont(_mono_font_bold)
        hbox.addWidget(self._name_lbl)
        hbox.addStretch()

        # progress bar
        self._pbar = _MinimalistProgressBar()
        self._pbar.setFixedSize(24, 8)

        # `+ 1` because we count this package build as its own
        # dependency so that, when all a package build's dependencies
        # are built, its state's progress bar is not complete
        self._pbar.setRange(0, len(self._pkg_build.info.dependencies) + 1)
        self._pbar.setValue(0)
        self._pbar.setTextVisible(False)
        hbox.addWidget(self._pbar)

        # right padding
        hbox.addSpacing(5)

        # set horizontal box as this widget's layout
        self.setLayout(hbox)

        # horizontal size policy is to ignore so that this widget takes
        # as much horizontal space as possible
        self.setSizePolicy(qtwidgets.QSizePolicy.Ignored,
                           qtwidgets.QSizePolicy.Fixed)
        self.setFixedHeight(24)

    def _is_built(self, pkg_build):
        stage = self._pkg_build_monitor.stage(pkg_build)
        return stage in (yobr.br.PkgBuildStage.BUILT, yobr.br.PkgBuildStage.INSTALLED)

    def update_from_state(self):
        # get build stage colour
        stage = self._pkg_build_monitor.stage(self._pkg_build)
        colour = _BUILD_STAGE_COLORS_BG[stage]

        # background label's style sheet
        bg_stylesheet = 'border-radius: 2px;'

        if self._is_selected:
            # selected: background is black, name has the build stage
            # colour
            name_stylesheet = 'color: {};'.format(colour)
            bg_stylesheet += 'background-color: rgba(0, 0, 0, .95);'
        else:
            # not selected: background has the build stage colour, name
            # is black
            name_stylesheet = 'color: rgba(0, 0, 0, .9)'
            bg_stylesheet += 'background-color: {};'.format(colour)

        # set label style sheets
        self._bg_lbl.setStyleSheet(bg_stylesheet)
        self._name_lbl.setStyleSheet(name_stylesheet)

        # update progress bar
        dep_built_count = 0

        for dep_pkg_info in self._pkg_build.info.dependencies:
            dep_pkg_build = self._pkg_build_monitor.pkg_builds[dep_pkg_info.name]

            if self._is_built(dep_pkg_build):
                dep_built_count += 1

        if self._is_built(self._pkg_build):
            # this package build is part of its own dependencies
            dep_built_count += 1

        self._pbar.setValue(dep_built_count)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        # update floating background label's size to fill this widget
        # completely
        self._bg_lbl.setFixedSize(self.size())

    def mouseReleaseEvent(self, event):
        self.clicked.emit()

    # any part of this widget is clicked
    clicked = qtcore.pyqtSignal()


# all the package build states
class _PkgBuildStateGrid(qtwidgets.QWidget):
    def __init__(self, pkg_build_monitor):
        super().__init__()
        self._pkg_build_monitor = pkg_build_monitor

        # this seems reasonable for most Buildroot package names
        self._min_item_width = 200

        # spacing around and between the package build states
        self._spacing = 5

        # start with no selected package build state
        self._selected_pkg_build_state = None

        # we know this widget's height, but its width can change as
        # desired
        self.setSizePolicy(qtwidgets.QSizePolicy.Ignored,
                           qtwidgets.QSizePolicy.Fixed)

        # create package build state widgets
        self._create_pkg_build_states()

    # a contained package build state is clicked
    def _pkg_build_state_clicked(self):
        if self._selected_pkg_build_state is not None:
            # unselect previous one
            self._selected_pkg_build_state.is_selected = False

        if self._selected_pkg_build_state is self.sender():
            # selected one was clicked: do not select any other
            self._selected_pkg_build_state = None
            self.no_pkg_build_state_selected.emit()
            return

        # select clicked package build
        self.selected_pkg_build = self.sender().pkg_build

    # a package build state is selected
    pkg_build_state_selected = qtcore.pyqtSignal(object)

    # no package build state is selected
    no_pkg_build_state_selected = qtcore.pyqtSignal()

    def _create_pkg_build_states(self):
        self._pkg_build_states = []

        # sort by package name
        for pkg_build in sorted(self._pkg_build_monitor.pkg_builds.values(), key=lambda pb: pb.info.name):
            # create the widget
            pkg_build_state = _PkgBuildState(pkg_build,
                                             self._pkg_build_monitor)

            # this widget is its parent: `pkg_build_state` now "floats"
            pkg_build_state.setParent(self)
            pkg_build_state.clicked.connect(self._pkg_build_state_clicked)
            self._pkg_build_states.append(pkg_build_state)

    def _pos_pkg_build_states(self):
        # use any package build state widget to know their common height
        item_height = self._pkg_build_states[0].height()

        # item height and spacing
        item_height_and_spacing = item_height + self._spacing

        # content width: widget's width without padding
        content_width = self.width() - 2 * self._spacing

        # number of package build states per row
        items_per_row = content_width // (self._min_item_width + self._spacing)

        if items_per_row == 0:
            # unlikely, but let's not divide by zero
            return

        # number of rows
        rows = math.ceil(len(self._pkg_build_states) / items_per_row)

        # now we know this widget's height
        self.setFixedHeight(rows * item_height_and_spacing + self._spacing)

        # a single package build state's width: remove spacing from
        # content width and divide by number of items per row
        item_width = (content_width - (items_per_row - 1) * self._spacing) // items_per_row

        # item width and spacing
        item_width_and_spacing = item_width + self._spacing

        # start at top-left corner (with padding)
        x = self._spacing
        y = self._spacing
        row_i = 0

        for pkg_build_state in self._pkg_build_states:
            if row_i >= items_per_row:
                # next row
                x = self._spacing
                y += item_height_and_spacing
                row_i = 0

            pkg_build_state.move(x, y)
            pkg_build_state.setFixedWidth(item_width)
            x += item_width_and_spacing

            # next column
            row_i += 1

    def resizeEvent(self, event):
        super().resizeEvent(event)

        # reposition grid items
        self._pos_pkg_build_states()

    def update_from_state(self):
        # update each package build state
        for pkg_build_state in self._pkg_build_states:
            pkg_build_state.update_from_state()

    # the currently selected package build, if any
    @property
    def selected_pkg_build(self):
        if self._selected_pkg_build_state is None:
            return

        return self._selected_pkg_build_state.pkg_build

    @selected_pkg_build.setter
    def selected_pkg_build(self, pkg_build):
        # find corresponding package build state
        for pkg_build_state in self._pkg_build_states:
            if pkg_build_state.pkg_build is pkg_build:
                break

        if self._selected_pkg_build_state is not None:
            # unselect previous one
            self._selected_pkg_build_state.is_selected = False

        # select new package build state
        self._selected_pkg_build_state = pkg_build_state
        self._selected_pkg_build_state.is_selected = True

        # signal
        self.pkg_build_state_selected.emit(self._selected_pkg_build_state)


# sets the text to and colour of a build stage label `lbl` for the
# build stage `stage` using the colours `colours`
def _set_build_stage_label(lbl, stage, colours=_BUILD_STAGE_COLORS_FG):
    stage_colour = colours[stage]
    lbl.setStyleSheet('color: {};'.format(stage_colour))
    lbl.setText(stage.value.capitalize())


# the details of a package build state
class _PkgBuildStateDetails(qtwidgets.QWidget):
    def __init__(self, pkg_build_monitor):
        super().__init__()
        self._pkg_build_monitor = pkg_build_monitor
        self._pkg_build = None
        self._build_ui()

    def _build_ui(self):
        def create_mono_label(is_bold=False):
            lbl = qtwidgets.QLabel()
            lbl.setFont(_mono_font_bold if is_bold else _mono_font)
            return lbl

        # main layout is a vertical box
        vbox = qtwidgets.QVBoxLayout()

        # package's name
        self._name_lbl = create_mono_label(True)
        font = self._name_lbl.font()
        font.setPointSize(12)
        self._name_lbl.setFont(font)
        vbox.addWidget(self._name_lbl)
        vbox.addSpacing(12)

        # textual information
        form = qtwidgets.QFormLayout()
        form.setVerticalSpacing(2)
        form.setHorizontalSpacing(16)
        self._stage_lbl = create_mono_label(True)
        form.addRow('Build stage:', self._stage_lbl)
        self._version_lbl = create_mono_label()
        form.addRow('Version:', self._version_lbl)
        self._install_target_lbl = create_mono_label()
        form.addRow('Install (target)?', self._install_target_lbl)
        self._install_staging_lbl = create_mono_label()
        form.addRow('Install (staging)?', self._install_staging_lbl)
        self._install_images_lbl = create_mono_label()
        form.addRow('Install (images)?', self._install_images_lbl)
        vbox.addLayout(form)

        # dependencies are within their own vertical box (empty for the
        # moment)
        self._dep_vbox = qtwidgets.QVBoxLayout()
        vbox.addLayout(self._dep_vbox)
        vbox.addStretch()

        # set main vertical box as this widget's layout
        self.setLayout(vbox)

    # a dependency package build state is clicked
    pkg_build_state_clicked = qtcore.pyqtSignal(object)

    def _pkg_build_state_clicked(self):
        self.pkg_build_state_clicked.emit(self.sender())

    # resets the dependency package build states; clears their vertical
    # box layout and creates new one for the dependencies of
    # `self._pkg_build.info`
    def _reset_deps(self):
        # get vertical box layout's current items
        items = []

        for i in range(self._dep_vbox.count()):
            items.append(self._dep_vbox.itemAt(i))

        # remove items
        for item in items:
            self._dep_vbox.removeItem(item)

            # we own `item` now: delete it later
            if item.layout() is not None:
                item.layout().deleteLater()

            if item.widget() is not None:
                item.widget().deleteLater()

        dep_pkg_infos = self._pkg_build.info.dependencies

        if len(dep_pkg_infos) == 0:
            # nothing to show
            return

        # title
        self._dep_vbox.addSpacing(12)
        text = 'Direct dependencies ({}):'.format(len(dep_pkg_infos))
        self._dep_vbox.addWidget(qtwidgets.QLabel(text))

        # create one package build state for each dependency (sorted by
        # name)
        for pkg_info in sorted(dep_pkg_infos, key=lambda pi: pi.name):
            pkg_build = self._pkg_build_monitor.pkg_builds[pkg_info.name]
            pkg_build_state = _PkgBuildState(pkg_build, self._pkg_build_monitor)
            pkg_build_state.clicked.connect(self._pkg_build_state_clicked)
            self._dep_vbox.addWidget(pkg_build_state)

        self._dep_vbox.addStretch()

    # package build which this widget explains
    @property
    def pkg_build(self):
        return self._pkg_build

    @pkg_build.setter
    def pkg_build(self, pkg_build):
        def update_bool_lbl(lbl, value):
            if value is None:
                text = '<i>N/A</i>'
            else:
                if value:
                    text = 'Yes'
                else:
                    text = 'No'

            lbl.setText(text)

        self._pkg_build = pkg_build
        info = self._pkg_build.info
        self._name_lbl.setText(info.name)

        if info.version is not None:
            version = info.version
        else:
            version = '<i>N/A</i>'

        self._version_lbl.setText(version)
        install_target = None
        install_staging = None
        install_images = None

        if type(info) is yobr.br.TargetPkgInfo:
            install_target = info.install_target
            install_staging = info.install_staging
            install_images = info.install_images

        update_bool_lbl(self._install_target_lbl, install_target)
        update_bool_lbl(self._install_staging_lbl, install_staging)
        update_bool_lbl(self._install_images_lbl, install_images)

        # reset dependency layout
        self._reset_deps()

        # update UI from state
        self.update_from_state()

    def _update_deps_from_state(self):
        for i in range(self._dep_vbox.count()):
            item = self._dep_vbox.itemAt(i)
            widget = item.widget()

            if type(widget) is _PkgBuildState:
                widget.update_from_state()

    def update_from_state(self):
        if self._pkg_build is None:
            # nothing to show
            return

        # update build stage
        stage = self._pkg_build_monitor.stage(self._pkg_build)
        _set_build_stage_label(self._stage_lbl, stage)

        # update dependency package build states
        self._update_deps_from_state()


# the build stage legend dialog
class _BuildStageLegendDialog(qtwidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Build stage legend')
        self.setModal(True)
        self.setSizeGripEnabled(False)

        # colors are easier to differentiate on a dark background
        self.setStyleSheet('QDialog { background-color: #202020; }')
        self._build_ui()

    def _build_ui(self):
        def add_label(stage):
            lbl = qtwidgets.QLabel()
            font = qtgui.QFont(_mono_font_bold)
            font.setPointSize(16)
            lbl.setFont(font)
            _set_build_stage_label(lbl, stage, _BUILD_STAGE_COLORS_BG)
            vbox.addWidget(lbl)

        vbox = qtwidgets.QVBoxLayout()
        add_label(yobr.br.PkgBuildStage.UNKNOWN)
        add_label(yobr.br.PkgBuildStage.DOWNLOADED)
        add_label(yobr.br.PkgBuildStage.EXTRACTED)
        add_label(yobr.br.PkgBuildStage.PATCHED)
        add_label(yobr.br.PkgBuildStage.CONFIGURED)
        add_label(yobr.br.PkgBuildStage.BUILT)
        add_label(yobr.br.PkgBuildStage.INSTALLED)
        self.setLayout(vbox)

    def showEvent(self, event):
        super().showEvent(event)

        # adjust this dialog's size to content
        self.setFixedSize(self.sizeHint())


# yobr's window
class _YoBrWindow(qtwidgets.QMainWindow):
    def __init__(self, app, pkg_build_monitor):
        super().__init__()
        self._app = app
        self._pkg_build_monitor = pkg_build_monitor
        self._build_ui()
        self.update_from_state()

    def _no_pkg_build_state_selected(self):
        # no selected package build state: hide details pane
        self._details_scroll_area.setVisible(False)

    def _pkg_build_state_selected(self, pkg_build_state):
        # selected package build state: show details pane to explain
        # this package build state
        self._details.pkg_build = pkg_build_state.pkg_build
        self._details_scroll_area.setVisible(True)

    def _build_ui(self):
        # set window's title from application name
        self.setWindowTitle(self._app.applicationName())

        # main layout is a vertical box
        main_layout = qtwidgets.QVBoxLayout()
        w = qtwidgets.QWidget()
        w.setLayout(main_layout)
        self.setCentralWidget(w)

        # build menu bar, progress (top), and package build state grid
        self._build_ui_menu_bar()
        self._build_ui_progress(main_layout)
        self._build_ui_pkg_build_state_grid()

        # wrap the grid within a scroll area
        scroll_area = qtwidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self._pkg_build_state_grid)

        # center of the window is the grid on the left and, possibly,
        # the details on the right
        hbox = qtwidgets.QHBoxLayout()
        hbox.addWidget(scroll_area)

        # build the details pane and add to center horizontal box
        self._build_ui_details()
        hbox.addWidget(self._details_scroll_area)
        main_layout.addLayout(hbox)

        # build status bar
        self._build_ui_status_bar()

    # refresh interval (ms) changed
    refresh_interval_changed = qtcore.pyqtSignal(int)

    def _emit_refresh_interval_changed(self, interval):
        self.refresh_interval_changed.emit(interval)

    def _build_ui_status_bar(self):
        self._status_bar = qtwidgets.QStatusBar()
        self.setStatusBar(self._status_bar)

    def _build_ui_pkg_build_state_grid(self):
        self._pkg_build_state_grid = _PkgBuildStateGrid(self._pkg_build_monitor)
        self._pkg_build_state_grid.pkg_build_state_selected.connect(self._pkg_build_state_selected)
        self._pkg_build_state_grid.no_pkg_build_state_selected.connect(self._no_pkg_build_state_selected)

    def _build_ui_details(self):
        def pkg_build_state_details_clicked(pkg_build_state):
            # change globally selected package build state
            self._pkg_build_state_grid.selected_pkg_build = pkg_build_state.pkg_build

        self._details = _PkgBuildStateDetails(self._pkg_build_monitor)
        self._details.pkg_build_state_clicked.connect(pkg_build_state_details_clicked)

        # wrap into a scroll area
        self._details_scroll_area = qtwidgets.QScrollArea()
        self._details_scroll_area.setWidgetResizable(True)
        self._details_scroll_area.setWidget(self._details)

        # no horizontal scrollbar: too ugly
        self._details_scroll_area.setHorizontalScrollBarPolicy(qtcore.Qt.ScrollBarAlwaysOff)

        # this seems to be enough
        self._details_scroll_area.setFixedWidth(300)

        # initially invisible
        self._details_scroll_area.setVisible(False)

    def _build_ui_progress(self, main_layout):
        self._pbar = qtwidgets.QProgressBar()
        self._pbar.setRange(0, len(self._pkg_build_monitor.pkg_builds))
        self._pbar.setFormat('%v/%m packages built')
        self._pbar.setValue(0)
        main_layout.addWidget(self._pbar)

    def _build_ui_menu_bar(self):
        def add_refresh_interval_action(name, interval):
            action = menu.addAction('Refresh every {}'.format(name))
            action.setCheckable(True)
            refresh_interval_action_group.addAction(action)
            action.triggered.connect(functools.partial(self._emit_refresh_interval_changed,
                                                       interval))
            return action

        def goto_website(url, checked):
            webbrowser.open_new_tab(url)

        def show_legend_window(checked):
            dlg = _BuildStageLegendDialog(self)
            dlg.exec()

        # file menu
        menu = self.menuBar().addMenu('&File')
        action = menu.addAction('&Quit')
        action.triggered.connect(self._app.quit)

        # state menu
        menu = self.menuBar().addMenu('&State')
        self._refresh_action = menu.addAction('&Refresh now')
        self._refresh_action.setShortcut(qtgui.QKeySequence.Refresh)
        menu.addSeparator()
        refresh_interval_action_group = qtwidgets.QActionGroup(self)
        refresh_interval_action_group.setExclusive(True)
        action = add_refresh_interval_action('500 ms', 500)
        action = add_refresh_interval_action('second', 1000)
        action = add_refresh_interval_action('two seconds', 2000)
        action.setChecked(True) # default
        action = add_refresh_interval_action('three seconds', 3000)
        action = add_refresh_interval_action('five seconds', 5000)
        action = add_refresh_interval_action('ten seconds', 10000)
        action = add_refresh_interval_action('30 seconds', 30000)
        action = add_refresh_interval_action('minute', 60000)

        # help menu
        menu = self.menuBar().addMenu('&Help')
        action = menu.addAction('Build stage &legend')
        action.triggered.connect(show_legend_window)
        menu.addSeparator()
        action = menu.addAction('Go to &project website')
        f = functools.partial(goto_website, 'https://github.com/eepp/yobr/')
        action.triggered.connect(f)
        action = menu.addAction('Go to &Buildroot website')
        f = functools.partial(goto_website, 'https://buildroot.org/')
        action.triggered.connect(f)

    # the "Refresh now" action
    @property
    def refresh_action(self):
        return self._refresh_action

    def update_from_state(self):
        # update status bar with the last refresh time
        now = datetime.datetime.now()
        status_text = now.strftime('Last update: %H:%M:%S')
        self._status_bar.showMessage(status_text)

        # update top progress bar
        self._pbar.setValue(self._pkg_build_monitor.built_count)

        # update package build states
        self._pkg_build_state_grid.update_from_state()

        # update package build state details
        self._details.update_from_state()


# prints an error message to the standard error
def _perror(msg):
    print('Error:', msg, file=sys.stderr)


# program's arguments
class _Args:
    def __init__(self, br_root_dir, br_build_dir):
        self._br_root_dir = br_root_dir
        self._br_build_dir = br_build_dir

    # Buildroot root directory
    @property
    def br_root_dir(self):
        return self._br_root_dir

    # Buildroot build directory
    @property
    def br_build_dir(self):
        return self._br_build_dir


# parses the command-line arguments for the application `app`
def _parse_args(app):
    parser = qtcore.QCommandLineParser()
    parser.setApplicationDescription('Graphical Buildroot build monitor')
    parser.addHelpOption()
    parser.addVersionOption()
    parser.addPositionalArgument('BR-ROOT-DIR', 'Buildroot root directory')
    parser.addPositionalArgument('BR-BUILD-DIR',
                                 'Buildroot build directory (default: `BR-ROOT-DIR/output/build`)')
    parser.process(app)
    pos_args = parser.positionalArguments()

    if len(pos_args) not in (1, 2):
        raise RuntimeError('Expecting one or two positional arguments.')

    if len(pos_args) == 2:
        # specific build directory
        br_build_dir = pos_args[1]
    else:
        # default to `BR-ROOT-DIR/output/build`
        br_build_dir = os.path.join(pos_args[0], 'output', 'build')

    return _Args(pos_args[0], br_build_dir)


def _validate_args(args):
    # the root directory must exist and be a directory
    os.path.isdir(args.br_root_dir)


def main():
    # refresh timer timeout
    def refresh_timer_timeout():
        logger.info('Updating package build monitor.')
        pkg_build_monitor.update()
        logger.info('Updating UI.')
        w.update_from_state()

    # some logging
    logging.basicConfig(format='[%(levelname)s] %(asctime)s: %(message)s')
    logger = logging.getLogger('main')
    logger.setLevel(logging.INFO)

    try:
        # create application
        logger.info('Starting application (v{}).'.format(yobr.__version__))
        app = qtwidgets.QApplication(sys.argv)
        app.setApplicationName('YO Buildroot!')
        app.setApplicationVersion(yobr.__version__)

        # parse and validate command-line arguments
        args = _parse_args(app)
        _validate_args(args)

        # query Buildroot for package information
        logger.info('Getting package information from `{}`.'.format(args.br_root_dir))
        pkg_build_monitor = yobr.br.pkg_build_monitor_from_make(args.br_root_dir,
                                                                args.br_build_dir)

        if len(pkg_build_monitor.pkg_builds) == 0:
            # weird
            raise RuntimeError('No packages found!')

        # update package monitor now
        pkg_build_monitor.update()
        logger.info('Watching {} packages:'.format(len(pkg_build_monitor.pkg_builds)))

        for pkg_build in sorted(pkg_build_monitor.pkg_builds.values(), key=lambda pb: pb.build_dir):
            logger.info('  `{}` ({} dependencies)'.format(pkg_build.build_dir,
                                                          len(pkg_build.info.dependencies)))

        # create window
        logger.info('Starting UI.')
        w = _YoBrWindow(app, pkg_build_monitor)

        # connect "Refresh now" action
        w.refresh_action.triggered.connect(refresh_timer_timeout)

        # create refresh timer: initial interval is 2 s
        timer = qtcore.QTimer(app)
        timer.setInterval(2000)
        timer.timeout.connect(refresh_timer_timeout)

        # connect interval change signal
        w.refresh_interval_changed.connect(timer.setInterval)

        # start timer
        timer.start()

        # show window
        w.show()

        # we're done
        sys.exit(app.exec_())
    except Exception as exc:
        _perror(str(exc))
        sys.exit(1)


if __name__ == '__main__':
    main()
