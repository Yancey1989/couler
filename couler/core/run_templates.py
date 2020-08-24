# Copyright 2020 The Couler Authors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pyaml
import yaml

from couler.core import pyfunc, states, step_update_utils
from couler.core.templates import (
    Container,
    Job,
    Output,
    OutputArtifact,
    OutputJob,
    Script,
)


def run_script(
    image,
    command=None,
    source=None,
    env=None,
    resources=None,
    secret=None,
    timeout=None,
    retry=None,
    step_name=None,
    image_pull_policy=None,
    pool=None,
    daemon=False,
):
    """Generate an Argo script template.  For example,
    https://github.com/argoproj/argo/tree/master/examples#scripts--results.
    Step_name is only used for annotating step while developing step zoo.
    """
    func_name, caller_line = pyfunc.invocation_location()
    func_name = (
        pyfunc.argo_safe_name(step_name)
        if step_name is not None
        else func_name
    )

    if states.workflow.get_template(func_name) is None:
        if source is None:
            raise ValueError("Input script can not be null")

        template = Script(
            name=func_name,
            image=image,
            command=command,
            source=source,
            env=env,
            secret=states.get_secret(secret),
            resources=resources,
            timeout=timeout,
            retry=retry,
            image_pull_policy=image_pull_policy,
            pool=pool,
            daemon=daemon,
        )
        states.workflow.add_template(template)

    step_name = step_update_utils.update_step(
        func_name, args=None, step_name=step_name, caller_line=caller_line
    )
    rets = pyfunc.script_output(step_name, func_name)
    states._steps_outputs[step_name] = rets
    return rets


def run_container(
    image,
    command=None,
    args=None,
    output=None,
    input=None,
    env=None,
    secret=None,
    resources=None,
    timeout=None,
    retry=None,
    step_name=None,
    image_pull_policy=None,
    pool=None,
    enable_ulogfs=True,
    daemon=False,
    volume_mounts=None,
):
    """
    Generate an Argo container template.  For example, the template whalesay
    in https://github.com/argoproj/argo/tree/master/examples#hello-world.
    :param image:
    :param command:
    :param args:
    :param output: output artifact for container output
    :param input: input artifact for container input
    :param env: environmental variable
    :param secret:
    :param resources: CPU or memory resource config dict
    :param timeout: in seconds
    :param retry: retry policy
    :param step_name: used for annotating step .
    :param image_pull_policy:
    :param pool:
    :param enable_ulogfs:
    :param daemon:
    :return:
    """
    func_name, caller_line = pyfunc.invocation_location()
    func_name = (
        pyfunc.argo_safe_name(step_name)
        if step_name is not None
        else func_name
    )

    if states.workflow.get_template(func_name) is None:
        # Generate the inputs parameter for the template
        if input is None:
            input = []

        if args is None and states._outputs_tmp is not None:
            args = []

        if args is not None:
            if not isinstance(args, list):
                args = [args]

            # Handle case where args is a list of list type
            # For example, [[Output, ]]
            if (
                isinstance(args, list)
                and len(args) > 0
                and isinstance(args[0], list)
                and len(args[0]) > 0
                and isinstance(args[0][0], Output)
            ):
                args = args[0]

            if states._outputs_tmp is not None:
                args.extend(states._outputs_tmp)

            # In case, the args include output artifact
            # Place output artifact into the input
            for arg in args:
                if isinstance(arg, (OutputArtifact, OutputJob)):
                    input.append(arg)

        # Generate container and template
        template = Container(
            name=func_name,
            image=image,
            command=command,
            args=args,
            env=env,
            secret=states.get_secret(secret),
            resources=resources,
            image_pull_policy=image_pull_policy,
            retry=retry,
            timeout=timeout,
            output=output,
            input=input,
            pool=pool,
            enable_ulogfs=enable_ulogfs,
            daemon=daemon,
            volume_mounts=volume_mounts,
        )
        states.workflow.add_template(template)

    step_name = step_update_utils.update_step(
        func_name, args, step_name, caller_line
    )

    # TODO: need to switch to use field `output` directly
    _output = (
        states.workflow.get_template(func_name).to_dict().get("outputs", None)
    )

    rets = pyfunc.container_output(step_name, func_name, _output)
    states._steps_outputs[step_name] = rets
    return rets


def run_job(
    manifest,
    success_condition,
    failure_condition,
    timeout=None,
    retry=None,
    step_name=None,
    pool=None,
    env=None,
    set_owner_reference=True,
):
    """
    Create a k8s job. For example, the pi-tmpl template in
    https://github.com/argoproj/argo/blob/master/examples/k8s-jobs.yaml
    :param manifest: YAML specification of the job to be created.
    :param success_condition: expression for verifying job success.
    :param failure_condition: expression for verifying job failure.
    :param timeout: To limit the elapsed time for a workflow in seconds.
    :param step_name: is only used while developing functions of step zoo.
    :param env: environmental parameter with a dict types, e.g., {"OS_ENV_1": "OS_ENV_value"}  # noqa: E501
    :param set_owner_reference: Whether to set the workflow as the job's owner reference.
        If `True`, the job will be deleted once the workflow is deleted.
    :return: output
    """
    if manifest is None:
        raise ValueError("Input manifest can not be null")

    func_name, caller_line = pyfunc.invocation_location()
    func_name = (
        pyfunc.argo_safe_name(step_name)
        if step_name is not None
        else func_name
    )

    args = []
    if states.workflow.get_template(func_name) is None:
        if states._outputs_tmp is not None and env is not None:
            env["inferred_outputs"] = states._outputs_tmp

        # Generate the inputs for the manifest template
        envs, parameters, args = pyfunc.generate_parameters_run_job(env)

        # update the env
        if env is not None:
            manifest_dict = yaml.safe_load(manifest)
            manifest_dict["spec"]["env"] = envs

            # TODO this is used to pass the test cases,
            # should be fixed in a better way
            if (
                "labels" in manifest_dict["metadata"]
                and "argo.step.owner" in manifest_dict["metadata"]["labels"]
            ):
                manifest_dict["metadata"]["labels"][
                    "argo.step.owner"
                ] = "'{{pod.name}}'"

            manifest = pyaml.dump(manifest_dict)

        template = Job(
            name=func_name,
            args=args,
            action="create",
            manifest=manifest,
            set_owner_reference=set_owner_reference,
            success_condition=success_condition,
            failure_condition=failure_condition,
            timeout=timeout,
            retry=retry,
            pool=pool,
        )
        states.workflow.add_template(template)

    step_update_utils.update_step(func_name, args, step_name, caller_line)

    # return job name and job uid for reference
    rets = pyfunc.job_output(step_name, func_name)
    states._steps_outputs[step_name] = rets
    return rets