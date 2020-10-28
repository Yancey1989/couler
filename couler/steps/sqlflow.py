'''This Module implements SQLFlow Step in Couler'''

from os import path

import couler.argo as couler


def escape_sql(original_sql):
    '''Escape special chars in SQL'''
    return original_sql.replace('\\', '\\\\').replace('"', r'\"').replace(
        "`", r'\`').replace("$", r'\$')


def sqlflow(sql,
            image="sqlflow/sqlflow",
            env=None,
            secret=None,
            resources=None,
            log_file=None):
    '''sqlflow step call run_container to append a workflow step.
    '''
    if not log_file:
        command = '''step -e "%s"''' % escape_sql(sql)
    else:
        # wait for some seconds to exit in case the
        # step pod is recycled too fast
        exit_time_wait = 0
        if isinstance(env, dict):
            exit_time_wait = env.get("SQLFLOW_WORKFLOW_EXIT_TIME_WAIT", "0")

        log_dir = path.dirname(log_file)
        command = "".join([
            "if [[ -f /opt/sqlflow/init_step_container.sh ]]; "
            "then bash /opt/sqlflow/init_step_container.sh; fi",
            " && set -o pipefail",  # fail when any sub-command fail
            " && mkdir -p %s" % log_dir,
            """ && (step -e "%s" 2>&1 | tee %s)""" %
            (escape_sql(sql), log_file),
            " && sleep %s" % exit_time_wait
        ])

    couler.run_container(command=command,
                         image=image,
                         env=env,
                         secret=secret,
                         resources=resources)
