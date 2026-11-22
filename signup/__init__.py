import datetime
import json
import os
import random
from mcdreforged.api.all import *

PLUGIN_METADATA = {
    'id': 'signup',
    'version': '1.6.0',
    'name': 'SignUp',
    'author': 'yello',
    "description": {
        "zh_cn": "一个让玩家每日签到与参与服务器工程的插件",
        "en_us": "A plugin for daily check-ins and server project management"
    },
    "dependencies": {
        "mcdreforged": ">=2.15.0"
    }
}

# 官网工程页基础地址：可在 config.json 的 website_url 中修改（默认 HTTPS）
DEFAULT_WEBSITE_URL = 'https://wanghaiserver.top:31480/'
PROJECT_PAGE_PATH = '/projects'

# 工程元数据默认值（旧 project.json 缺字段时自动补全）
PROJECT_META_DEFAULTS: dict = {
    'description': '',
    'remark': '',
    'created_at': '',
    'updated_at': '',
    'claimed_at': None,
    'completed_at': None,
}

config = {}
data: dict[str, dict] = {}
data_path = ''
projects: list[dict[str, str | list[str]]] = []
project_path = ''


class SignUpError(Exception):
    """工程数据层错误：携带稳定错误码，供官网 WS 桥接层透传。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def get_today_str() -> str:
    return datetime.date.today().strftime('%Y-%m-%d')


def get_now_time_str() -> str:
    return datetime.datetime.now().strftime('%H:%M:%S')


def get_yesterday_str() -> str:
    return (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')


def get_effective_days(pdata: dict) -> int:
    last_date = pdata.get('last_signup_date')
    if last_date is None:
        return 0
    today = get_today_str()
    yesterday = get_yesterday_str()
    if last_date in (today, yesterday):
        return pdata.get('consecutive_days', 0)
    return 0


def save_data():
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_projects():
    with open(project_path, 'w', encoding='utf-8') as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)


def get_project(name: str) -> dict | None:
    for p in projects:
        if p.get('name') == name:
            return p
    return None


# ---------------------------------------------------------------------------
# 工程数据层（供游戏内指令与官网 WS 桥接共用；权限由调用方判断）
# ---------------------------------------------------------------------------

def get_now_iso() -> str:
    """当前本地时间（ISO 8601，精确到秒），用于工程元数据。"""
    return datetime.datetime.now().isoformat(timespec='seconds')


def get_project_page_url() -> str:
    """官网工程页地址（基础地址来自 config.json 的 website_url）。"""
    base = str(config.get('website_url') or DEFAULT_WEBSITE_URL).strip() or DEFAULT_WEBSITE_URL
    return base.rstrip('/') + PROJECT_PAGE_PATH


def get_project_page_link() -> RText:
    """可点击的官网工程页 RText（游戏中所有相关提示统一使用）。"""
    url = get_project_page_url()
    return RText('官网工程页', color=RColor.aqua).c(RAction.open_url, url).h('点击打开 {}'.format(url))


def normalize_project(project: dict) -> bool:
    """补全旧数据的元数据字段；返回是否发生了修改。"""
    changed = False
    for key, default in PROJECT_META_DEFAULTS.items():
        if key not in project:
            project[key] = default
            changed = True
    if not isinstance(project.get('claimants'), list):
        project['claimants'] = []
        changed = True
    return changed


def list_projects() -> list[dict]:
    """返回全部工程的拷贝（避免官网桥接层直接修改插件内存数据）。"""
    return [
        {**project, 'claimants': list(project.get('claimants') or [])}
        for project in projects
    ]


def create_project(name: str, creator: str) -> dict:
    """创建工程（调用方负责权限校验）；名称去空白后不能为空且不能重名。"""
    name = (name or '').strip()
    creator = (creator or '').strip()
    if not name:
        raise SignUpError('project_name_invalid')
    if not creator:
        raise SignUpError('project_player_invalid')
    if get_project(name) is not None:
        raise SignUpError('project_exists')
    now = get_now_iso()
    project = {
        'name': name,
        'creator': creator,
        'status': 'unclaimed',
        'claimants': [],
        **PROJECT_META_DEFAULTS,
        'created_at': now,
        'updated_at': now,
    }
    projects.append(project)
    save_projects()
    return project


def claim_project(name: str, player: str) -> dict:
    """认领工程：未完成、同一玩家名不能重复认领；首个认领把状态置为 claimed。"""
    project = get_project((name or '').strip())
    if project is None:
        raise SignUpError('project_not_found')
    player = (player or '').strip()
    if not player:
        raise SignUpError('project_player_invalid')
    if project.get('status') == 'completed':
        raise SignUpError('project_completed')
    claimants = project.setdefault('claimants', [])
    if player in claimants:
        raise SignUpError('project_already_claimed')
    now = get_now_iso()
    claimants.append(player)
    if project.get('status') == 'unclaimed':
        project['status'] = 'claimed'
    if not project.get('claimed_at'):
        project['claimed_at'] = now
    project['updated_at'] = now
    save_projects()
    return project


def complete_project(name: str) -> dict:
    """完成工程：必须已被认领且未完成（调用方负责发起者 / 权限校验）。"""
    project = get_project((name or '').strip())
    if project is None:
        raise SignUpError('project_not_found')
    if project.get('status') == 'unclaimed':
        raise SignUpError('project_not_claimed')
    if project.get('status') == 'completed':
        raise SignUpError('project_completed')
    now = get_now_iso()
    project['status'] = 'completed'
    project['completed_at'] = now
    project['updated_at'] = now
    save_projects()
    return project


def delete_project(name: str) -> dict:
    """删除工程（调用方负责权限校验）。"""
    project = get_project((name or '').strip())
    if project is None:
        raise SignUpError('project_not_found')
    projects.remove(project)
    save_projects()
    return project


def update_project_meta(name: str, description: str | None = None, remark: str | None = None) -> dict:
    """更新工程描述 / 备注（仅官网调用）；参数为 None 表示不修改该字段。"""
    project = get_project((name or '').strip())
    if project is None:
        raise SignUpError('project_not_found')
    changed = False
    if description is not None:
        project['description'] = str(description)
        changed = True
    if remark is not None:
        project['remark'] = str(remark)
        changed = True
    if changed:
        project['updated_at'] = get_now_iso()
        save_projects()
    return project


def check_perm(source: CommandSource) -> bool:
    return source.get_permission_level() >= config.get('permission', 3)


def handle_signup(source: CommandSource):
    server = source.get_server()

    if not source.is_player:
        source.reply('[SignUp]§c该指令只能由玩家执行§r')
        return

    player_name = str(source.player)

    if player_name not in data:
        data[player_name] = {
            'consecutive_days': 0,
            'last_signup_date': None,
            'last_signup_time': None,
            'total_signups': 0,
        }

    pdata = data[player_name]
    today = get_today_str()
    last_date = pdata.get('last_signup_date')

    if last_date == today:
        source.reply(
            '[SignUp]§e你今天已经签到过了！连续签到 §a{}§e 天§r'.format(pdata['consecutive_days'])
        )
        return

    yesterday = get_yesterday_str()
    if last_date is not None and last_date not in (yesterday, today):
        pdata['consecutive_days'] = 0

    pdata['consecutive_days'] += 1
    pdata['last_signup_date'] = today
    pdata['last_signup_time'] = get_now_time_str()
    pdata['total_signups'] = pdata.get('total_signups', 0) + 1

    save_data()

    consecutive = pdata['consecutive_days']
    prizes = config.get('prizes', {})

    def give(prize):
        if isinstance(prize, list):
            prize = random.choice(prize) if prize else ''
        if prize and str(prize).strip():
            server.execute('give {} {}'.format(player_name, prize))
            source.reply('[SignUp]§d获得奖励: §e{}§r'.format(prize))

    if consecutive > 0 and consecutive % 365 == 0:
        give(prizes.get('year', ''))
        source.reply('[SignUp]§d恭喜连续签到 {} 天！§r'.format(consecutive))
    elif consecutive > 0 and consecutive % 30 == 0:
        give(prizes.get('month', ''))
        source.reply('[SignUp]§d恭喜连续签到 {} 天！§r'.format(consecutive))
    elif consecutive > 0 and consecutive % 7 == 0:
        give(prizes.get('week', ''))
        source.reply('[SignUp]§d恭喜连续签到 {} 天！§r'.format(consecutive))
    else:
        give(prizes.get('regular', ''))

    source.reply(
        '[SignUp]§a签到成功！连续签到 §e{}§a 天（累计 §b{}§a 次）§r'.format(
            pdata['consecutive_days'], pdata['total_signups']
        )
    )


def handle_list(source: CommandSource):
    if not data:
        source.reply('[SignUp]§e还没有人签到过呢！')
        return

    rank = []
    for name, pdata in data.items():
        eff_days = get_effective_days(pdata)
        total = pdata.get('total_signups', 0)
        rank.append((name, eff_days, total))

    rank.sort(key=lambda x: x[1], reverse=True)

    source.reply('§6===== §l签到排行榜（前10名）§6=====§r')
    for i, (name, days, total) in enumerate(rank[:10], 1):
        source.reply(
            '§e第{}名. §f{} §7- 连续签到 §a{}§7 天（累计 §b{}§7 次）§r'.format(i, name, days, total)
        )


def handle_today(source: CommandSource):
    today = get_today_str()

    today_list = []
    for name, pdata in data.items():
        if pdata.get('last_signup_date') == today:
            today_list.append((name, pdata.get('last_signup_time', '')))

    if not today_list:
        source.reply('[SignUp]§e今天还没有人签到！')
        return

    today_list.sort(key=lambda x: x[1])

    source.reply('§6===== §l今日签到排行（前10名）§6=====§r')
    for i, (name, time_str) in enumerate(today_list[:10], 1):
        source.reply('§e第{}名. §f{} §7- §a{}§r'.format(i, name, time_str))


def handle_get(source: CommandSource, context: CommandContext):
    player_name = context['player']

    if player_name not in data:
        source.reply('[SignUp]§c玩家 §e{}§c 还没有签到记录！§r'.format(player_name))
        return

    pdata = data[player_name]
    eff_days = get_effective_days(pdata)
    today = get_today_str()
    last_date = pdata.get('last_signup_date')
    last_time = pdata.get('last_signup_time')
    total = pdata.get('total_signups', 0)

    source.reply('§6===== §l{} 的签到信息 §6=====§r'.format(player_name))
    source.reply('§7连续签到天数: §a{}§r'.format(eff_days))
    source.reply('§7累计签到次数: §b{}§r'.format(total))
    if last_date is not None:
        source.reply('§7最近签到时间: §e{} {}§r'.format(last_date, last_time))
    if last_date == today:
        source.reply('§a今日已签到§r')
    else:
        source.reply('§c今日未签到§r')


def handle_help(source: CommandSource):
    source.reply('§6===== §lSignUp 签到/工程插件帮助 §6=====§r')
    source.reply(RTextList(
        RText('!!signup', color=RColor.yellow).c(RAction.suggest_command, '!!signup'),
        '§7 - 每日签到§r'
    ))
    source.reply(RTextList(
        RText('!!signup help', color=RColor.yellow).c(RAction.suggest_command, '!!signup help'),
        '§7 - 显示此帮助信息§r'
    ))
    source.reply(RTextList(
        RText('!!signup list', color=RColor.yellow).c(RAction.suggest_command, '!!signup list'),
        '§7 - 查看历史签到排行榜（按连续天数降序，断签归零）§r'
    ))
    source.reply(RTextList(
        RText('!!signup today', color=RColor.yellow).c(RAction.suggest_command, '!!signup today'),
        '§7 - 查看今日签到时间排行榜（最早在前）§r'
    ))
    source.reply(RTextList(
        RText('!!signup get <玩家>', color=RColor.yellow).c(RAction.suggest_command, '!!signup get '),
        '§7 - 查询指定玩家的签到信息§r'
    ))
    source.reply(RTextList(
        RText('!!signup project', color=RColor.yellow).c(RAction.suggest_command, '!!signup project'),
        '§7 - 打开工程管理面板§r'
    ))
    source.reply(RTextList(
        '§7工程描述 / 备注仅可在 ',
        get_project_page_link(),
        ' §7修改，时间由插件自动记录（游戏内不可编辑）§r'
    ))

STATUS_NAMES = {
    'unclaimed': '§e待认领§r',
    'claimed': '§c已认领§r',
    'completed': '§a已完成§r',
}

def handle_project(source: CommandSource, context: CommandContext):
    source.reply('§6===== §lSignUp 工程管理系统 §6=====§r')
    source.reply(RTextList(
        RText('!!signup project set <名称>', color=RColor.yellow).c(RAction.suggest_command, '!!signup project set '),
        '§7 - 创建新工程§r'
    ))
    source.reply(RTextList(
        RText('!!signup project delete <名称>', color=RColor.yellow).c(RAction.suggest_command, '!!signup project delete '),
        '§7 - 删除工程（仅待认领）§r'
    ))
    source.reply(RTextList(
        RText('!!signup project list [<all | claimed | unclaimed | completed>]', color=RColor.yellow).c(RAction.suggest_command, '!!signup project list '),
        '§7 - 按状态筛选工程§r'
    ))
    source.reply(RTextList(
        RText('!!signup project get <名称>', color=RColor.yellow).c(RAction.suggest_command, '!!signup project get '),
        '§7 - 查看工程详情§r'
    ))
    source.reply(RTextList(
        RText('!!signup project claim <名称>', color=RColor.yellow).c(RAction.suggest_command, '!!signup project claim '),
        '§7 - 认领工程（未完成即可）§r'
    ))
    source.reply(RTextList(
        RText('!!signup project complete <名称>', color=RColor.yellow).c(RAction.suggest_command, '!!signup project complete '),
        '§7 - 完成工程§r'
    ))
    source.reply(RTextList(
        '§7工程描述 / 备注仅可在 ',
        get_project_page_link(),
        ' §7修改，时间由插件自动记录（游戏内不可编辑）§r'
    ))

def _show_project_list(source: CommandSource, filter_key: str):
    if filter_key == 'all':
        filtered = projects
    else:
        filtered = [p for p in projects if p['status'] == filter_key]

    if not filtered:
        source.reply('[SignUp]§e没有符合条件的工程！§r')
        return

    title_map = {'all': '全部', 'unclaimed': '待认领', 'claimed': '已认领', 'completed': '已完成'}
    source.reply('§6===== §l{}工程列表（点击名称查看详情）§6=====§r'.format(title_map.get(filter_key, filter_key)))
    for i, p in enumerate(filtered, 1):
        claimants_str = ', '.join(p.get('claimants', [])) or '无'
        source.reply(RTextList(
            '§e{}. '.format(i),
            RText(p['name'], color=RColor.white).c(RAction.suggest_command, '!!signup project get {}'.format(p['name'])).h('点击查看详情'),
            ' §7| 发起者: §b{} §7| 状态: {} §7| 认领者: §f{}§r'.format(p['creator'], STATUS_NAMES.get(p['status'], p['status']), claimants_str)
        ))

def handle_project_list(source: CommandSource, context: CommandContext):
    filter_key = context.get('filter', 'unclaimed').lower()
    if filter_key not in ('all', 'unclaimed', 'claimed', 'completed'):
        source.reply('[SignUp]§c无效筛选条件！可用: all, unclaimed, claimed, completed§r')
        return
    _show_project_list(source, filter_key)


def _project_error_message(code: str, name: str = '') -> str:
    """把工程数据层错误码转换为游戏内提示（与原有文案保持一致）。"""
    if code == 'project_not_found':
        return '[SignUp]§c工程 §e{}§c 不存在！§r'.format(name)
    if code == 'project_exists':
        return '[SignUp]§c工程 §e{}§c 已存在！§r'.format(name)
    if code == 'project_name_invalid':
        return '[SignUp]§c工程名称不能为空！§r'
    if code == 'project_player_invalid':
        return '[SignUp]§c玩家名称无效！§r'
    if code == 'project_already_claimed':
        return '[SignUp]§e你已经认领过这个工程了！§r'
    if code == 'project_not_claimed':
        return '[SignUp]§c该工程尚未被认领，无法完成！§r'
    if code == 'project_completed':
        return '[SignUp]§c该工程已完成，无法继续操作！§r'
    return '[SignUp]§c操作失败（{}）§r'.format(code)

def handle_project_set(source: CommandSource, context: CommandContext):
    if not source.is_player:
        source.reply('[SignUp]§c该指令只能由玩家执行§r')
        return
    if not check_perm(source):
        source.reply('[SignUp]§c你没有权限创建工程！（需要权限等级 ≥ {}）§r'.format(config.get('permission', 3)))
        return
    name = context['project_name']
    if get_project(name):
        source.reply('[SignUp]§c工程 §e{}§c 已存在！§r'.format(name))
        return
    try:
        project = create_project(name, str(source.player))
    except SignUpError as exc:
        source.reply(_project_error_message(exc.code, name))
        return
    source.reply('[SignUp]§a工程 §e{}§a 创建成功！§r'.format(project['name']))


def handle_project_get(source: CommandSource, context: CommandContext):
    name = context['project_name']
    prj = get_project(name)
    if not prj:
        source.reply('[SignUp]§c工程 §e{}§c 不存在！§r'.format(name))
        return
    claimants_str = ', '.join(prj.get('claimants', [])) or '无'
    source.reply('§6===== §l{} 的工程信息 §6=====§r'.format(name))
    source.reply('§7发起者: §b{}§r'.format(prj['creator']))
    source.reply('§7状态: {}§r'.format(STATUS_NAMES.get(prj['status'], prj['status'])))
    source.reply('§7认领者: §f{}§r'.format(claimants_str))
    if prj.get('created_at'):
        source.reply('§7创建时间: §e{}§r'.format(prj['created_at']))
    if prj.get('claimed_at'):
        source.reply('§7认领时间: §e{}§r'.format(prj['claimed_at']))
    if prj.get('completed_at'):
        source.reply('§7完成时间: §a{}§r'.format(prj['completed_at']))
    source.reply(RTextList(
        '§7描述 / 备注请在 ',
        get_project_page_link(),
        ' §7查看（游戏内不可修改）§r'
    ))

    buttons = []
    cmd_prefix = '!!signup project '
    if prj['status'] in ('unclaimed', 'claimed'):
        buttons.append(RText('[认领]', color=RColor.yellow)
            .c(RAction.suggest_command, '{}claim {}'.format(cmd_prefix, name)).h('点击认领'))
        buttons.append(' ')
        buttons.append(RText('[完成]', color=RColor.green)
            .c(RAction.suggest_command, '{}complete {}'.format(cmd_prefix, name)).h('点击完成'))
    if prj['status'] == 'unclaimed' or source.get_permission_level() >= 4:
        buttons.append(' ')
        buttons.append(RText('[删除]', color=RColor.red)
            .c(RAction.suggest_command, '{}delete {}'.format(cmd_prefix, name)).h('点击删除'))
    if buttons:
        source.reply(RTextList(*buttons))


def handle_project_delete(source: CommandSource, context: CommandContext):
    name = context['project_name']
    prj = get_project(name)
    if not prj:
        source.reply('[SignUp]§c工程 §e{}§c 不存在！§r'.format(name))
        return
    force = source.get_permission_level() >= 4
    if not force:
        if not (check_perm(source) or str(source.player) == prj['creator']):
            source.reply('[SignUp]§c你没有权限删除工程！§r')
            return
        if prj['status'] != 'unclaimed':
            source.reply('[SignUp]§c只能删除待认领的工程！§r')
            return
    try:
        delete_project(name)
    except SignUpError as exc:
        source.reply(_project_error_message(exc.code, name))
        return
    source.reply('[SignUp]§a工程 §e{}§a 已删除！§r'.format(name))

def handle_project_claim(source: CommandSource, context: CommandContext):
    if not source.is_player:
        source.reply('[SignUp]§c该指令只能由玩家执行§r')
        return
    name = context['project_name']
    prj = get_project(name)
    if not prj:
        source.reply('[SignUp]§c工程 §e{}§c 不存在！§r'.format(name))
        return
    if prj['status'] == 'completed':
        source.reply('[SignUp]§c该工程已完成，无法认领！§r')
        return
    player_name = str(source.player)
    if player_name in prj.get('claimants', []):
        source.reply('[SignUp]§e你已经认领过这个工程了！§r')
        return
    try:
        claim_project(name, player_name)
    except SignUpError as exc:
        source.reply(_project_error_message(exc.code, name))
        return
    source.reply('[SignUp]§a你已成功认领工程 §e{}§a！§r'.format(name))

def handle_project_complete(source: CommandSource, context: CommandContext):
    name = context['project_name']
    prj = get_project(name)
    if not prj:
        source.reply('[SignUp]§c工程 §e{}§c 不存在！§r'.format(name))
        return
    if prj['status'] == 'unclaimed':
        source.reply('[SignUp]§c该工程尚未被认领，无法完成！§r')
        return
    if prj['status'] == 'completed':
        source.reply('[SignUp]§e该工程已经完成了！§r')
        return
    player_name = str(source.player)
    if not (player_name == prj['creator'] or check_perm(source)):
        source.reply('[SignUp]§c只有发起者或管理员可以完成工程！§r')
        return
    try:
        complete_project(name)
    except SignUpError as exc:
        source.reply(_project_error_message(exc.code, name))
        return
    source.reply('[SignUp]§a工程 §e{}§a 已标记为完成！§r'.format(name))


def on_player_joined(server: PluginServerInterface, player: str, info: Info):
    if not config.get('remind_on_join', True):
        return

    today = get_today_str()

    if player not in data or data[player].get('last_signup_date') != today:
        server.tell(player, RTextList(
            '§e[SignUp]你今天还没有签到哦！使用§r ',
            RText('!!signup', color=RColor.gray).c(RAction.suggest_command, '!!signup'),
            '§e 签到吧~§r'
        ))


def on_load(server: PluginServerInterface, old):
    global config, data, data_path, projects, project_path

    data_path = os.path.join(server.get_data_folder(), 'data.json')
    project_path = os.path.join(server.get_data_folder(), 'project.json')
    os.makedirs(os.path.dirname(data_path), exist_ok=True)

    default_config = {
        'remind_on_join': True,
        'permission': 3,
        'website_url': DEFAULT_WEBSITE_URL,
        'prizes': {
            'regular': '',
            'week': '',
            'month': '',
            'year': ''
        }
    }
    config = server.load_config_simple('config.json', default_config, in_data_folder=True)

    if os.path.exists(data_path):
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = {}
        save_data()

    if os.path.exists(project_path):
        with open(project_path, 'r', encoding='utf-8') as f:
            projects = json.load(f)
    else:
        projects = []
        save_projects()

    # 旧 project.json 迁移：补全官网可编辑的描述 / 备注 / 时间字段，只回写一次
    migrated = False
    for project in projects:
        migrated = normalize_project(project) or migrated
    if migrated:
        save_projects()

    server.register_help_message('!!signup', '每日签到 & 工程管理')

    builder = SimpleCommandBuilder()

    builder.arg('player', Text)

    builder.arg('project_name', GreedyText)
    builder.arg('filter', Text)

    builder.command('!!signup', handle_signup)
    builder.command('!!signup help', handle_help)
    builder.command('!!signup list', handle_list)
    builder.command('!!signup today', handle_today)
    builder.command('!!signup get <player>', handle_get)

    builder.command('!!signup project', handle_project)

    builder.command('!!signup project set', handle_project)
    builder.command('!!signup project set <project_name>', handle_project_set)
    
    builder.command('!!signup project delete', handle_project)
    builder.command('!!signup project delete <project_name>', handle_project_delete)

    builder.command('!!signup project list', handle_project_list)
    builder.command('!!signup project list <filter>', handle_project_list)

    builder.command('!!signup project claim', handle_project)
    builder.command('!!signup project claim <project_name>', handle_project_claim)

    builder.command('!!signup project get', handle_project)
    builder.command('!!signup project get <project_name>', handle_project_get)
    
    builder.command('!!signup project complete', handle_project)
    builder.command('!!signup project complete <project_name>', handle_project_complete)

    builder.register(server)

    server.register_event_listener(MCDRPluginEvents.PLAYER_JOINED, on_player_joined)
