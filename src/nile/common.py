"""nile common module."""
import json
import logging
import os
import re
import subprocess

from starkware.crypto.signature.fast_pedersen_hash import pedersen_hash
from starkware.starknet.core.os.class_hash import compute_class_hash
from starkware.starknet.services.api.contract_class import ContractClass

from nile.utils import hex_class_hash, normalize_number, str_to_felt

CONTRACTS_DIRECTORY = "contracts"
BUILD_DIRECTORY = "artifacts"
TEMP_DIRECTORY = ".temp"
ABIS_DIRECTORY = f"{BUILD_DIRECTORY}/abis"
DEPLOYMENTS_FILENAME = "deployments.txt"
DECLARATIONS_FILENAME = "declarations.txt"
ACCOUNTS_FILENAME = "accounts.json"
NODE_FILENAME = "node.json"
RETRY_AFTER_SECONDS = 30
TRANSACTION_VERSION = 1
QUERY_VERSION_BASE = 2**128
QUERY_VERSION = QUERY_VERSION_BASE + TRANSACTION_VERSION
UNIVERSAL_DEPLOYER_ADDRESS = (
    # subject to change
    "0x041a78e741e5af2fec34b695679bc6891742439f7afb8484ecd7766661ad02bf"
)


def get_gateways():
    """Get the StarkNet node details."""
    try:
        with open(NODE_FILENAME, "r") as f:
            gateway = json.load(f)
            return gateway

    except FileNotFoundError:
        with open(NODE_FILENAME, "w") as f:
            networks = {
                "localhost": "http://127.0.0.1:5050/",
                "goerli2": "https://alpha4-2.starknet.io",
                "integration": "https://external.integration.starknet.io",
            }
            f.write(json.dumps(networks, indent=2))

            return networks


GATEWAYS = get_gateways()


def get_all_contracts(ext=None, directory=None):
    """Get all cairo contracts in the default contract directory."""
    if ext is None:
        ext = ".cairo"

    files = list()
    for (dirpath, _, filenames) in os.walk(
        directory if directory else CONTRACTS_DIRECTORY
    ):
        files += [
            os.path.join(dirpath, file) for file in filenames if file.endswith(ext)
        ]

    return files


def run_command(
    operation,
    network,
    contract_name=None,
    arguments=None,
    inputs=None,
    signature=None,
    max_fee=None,
    query_flag=None,
    overriding_path=None,
    mainnet_token=None,
):
    """Execute CLI command with given parameters."""
    command = ["starknet", operation]

    if contract_name is not None:
        base_path = (
            overriding_path if overriding_path else (BUILD_DIRECTORY, ABIS_DIRECTORY)
        )
        contract = f"{base_path[0]}/{contract_name}.json"
        command.append("--contract")
        command.append(contract)

    if inputs is not None:
        command.append("--inputs")
        command.extend(prepare_params(inputs))

    if signature is not None:
        command.append("--signature")
        command.extend(prepare_params(signature))

    if max_fee is not None:
        command.append("--max_fee")
        command.append(max_fee)

    if mainnet_token is not None:
        command.append("--token")
        command.append(mainnet_token)

    if query_flag is not None:
        command.append(f"--{query_flag}")

    if arguments is not None:
        command.extend(arguments)

    command += get_network_parameter_or_set_env(network)

    command.append("--no_wallet")

    try:
        return subprocess.check_output(command).strip().decode("utf-8")
    except subprocess.CalledProcessError:
        p = subprocess.Popen(command, stderr=subprocess.PIPE)
        _, error = p.communicate()
        err_msg = error.decode()

        if "max_fee must be bigger than 0" in err_msg:
            logging.error(
                """
                \n😰 Whoops, looks like max fee is missing. Try with:\n
                --max_fee=`MAX_FEE`
                """
            )
        elif "transactions should go through the __execute__ entrypoint." in err_msg:
            logging.error(
                "\n\n😰 Whoops, looks like you're not using an account. Try with:\n"
                "\nnile send [OPTIONS] SIGNER CONTRACT_NAME METHOD [PARAMS]"
            )

        return ""


def parse_information(x):
    """Extract information from deploy/declare command."""
    # address is 64, tx_hash is 64 chars long
    address, tx_hash = re.findall("0x[\\da-f]{1,64}", str(x))
    return normalize_number(address), normalize_number(tx_hash)


def stringify(x, process_short_strings=False):
    """Recursively convert list or tuple elements to strings."""
    if isinstance(x, list) or isinstance(x, tuple):
        return [stringify(y, process_short_strings) for y in x]
    else:
        if process_short_strings and is_string(x):
            return str(str_to_felt(x))
        return str(x)


def prepare_params(params):
    """Sanitize call, invoke, and deploy parameters."""
    if params is None:
        params = []
    return stringify(params, True)


def is_string(param):
    """Identify a param as string if is not int or hex."""
    is_int = True
    is_hex = True

    # convert to integer
    try:
        int(param)
    except Exception:
        is_int = False

    # convert to hex (starting with 0x)
    try:
        assert param.startswith("0x")
        int(param, 16)
    except Exception:
        is_hex = False

    return not is_int and not is_hex


def is_alias(param):
    """Identify param as alias (instead of address)."""
    return is_string(param)


def get_network_parameter_or_set_env(network):
    """Update environment variables or return network parameter for StarkNet-cli."""
    extra_param = []
    if network == "mainnet":
        os.environ["STARKNET_NETWORK"] = "alpha-mainnet"
    elif network == "goerli":
        os.environ["STARKNET_NETWORK"] = "alpha-goerli"
    else:
        extra_param = [
            f"--gateway_url={GATEWAYS.get(network)}",
            f"--feeder_gateway_url={GATEWAYS.get(network)}",
        ]
    return extra_param


def get_contract_class(contract_name, overriding_path=None):
    """Return the contract_class for a given contract name."""
    base_path = (
        overriding_path if overriding_path else (BUILD_DIRECTORY, ABIS_DIRECTORY)
    )
    with open(f"{base_path[0]}/{contract_name}.json", "r") as fp:
        contract_class = ContractClass.loads(fp.read())

    return contract_class


def get_hash(contract_name, overriding_path=None):
    """Return the class_hash for a given contract name."""
    contract_class = get_contract_class(contract_name, overriding_path)
    return hex_class_hash(
        compute_class_hash(contract_class=contract_class, hash_func=pedersen_hash)
    )


def get_addresses_from_string(string):
    """Return a set of integers with identified addresses in a string."""
    return set(
        int(address, 16) for address in re.findall("0x[\\da-f]{1,64}", str(string))
    )
