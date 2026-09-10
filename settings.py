from os import environ

DEBUG = False

SESSION_CONFIGS = [
    dict(
        name='contagion_10',
        display_name='Contagion (10 players)',
        app_sequence=['contagion'],
        num_demo_participants=10,
        network_name='contagion',
        timer=6,
        blocks=6,
        rounds_per_block=10,
        num_rounds=64,
        payoff_in=1,
        payoff_out=3,
    ),
]

SESSION_CONFIG_DEFAULTS = dict(
    real_world_currency_per_point=0,   # no cash conversion
    participation_fee=0,              # show-up fee
    doc="",
)

PARTICIPANT_FIELDS = []
SESSION_FIELDS = []

LANGUAGE_CODE = 'en'

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = environ.get('OTREE_ADMIN_PASSWORD')

DEMO_PAGE_INTRO_HTML = ""

SECRET_KEY = '8675309jennyidontknow'  # Change this to any random string

ROOMS = [
    {
        'name': 'econ_lab',
        'display_name': 'Econ Lab 1',
    },
    {
        'name': 'econ_lab2',
        'display_name': 'Econ Lab 2',
    },
    {
        'name': 'econ_lab3',
        'display_name': 'Econ Lab 3',
    },
    {
        'name': 'econ_lab4',
        'display_name': 'Econ Lab 4',
    },
]

'''ROOMS = [
    {
        'name': 'econ_lab',
        'display_name': 'Econ Lab 1',
        'participant_label_file': '_rooms/econ_lab.txt',
    },
    {
        'name': 'econ_lab2',
        'display_name': 'Econ Lab 2',
        'participant_label_file': '_rooms/econ_lab2.txt',
    },
    {
        'name': 'econ_lab3',
        'display_name': 'Econ Lab 3',
        'participant_label_file': '_rooms/econ_lab3.txt',
    },
    {
        'name': 'econ_lab4',
        'display_name': 'Econ Lab 4',
        'participant_label_file': '_rooms/econ_lab4.txt',
    },
]'''
INSTALLED_APPS = ['otree']

