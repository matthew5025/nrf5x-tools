#!/usr/bin/env python3.5
"""
NRF5-parser tool. 
This script will parse the development kits of Nordic Semiconductor 
from the 'developer.nordicsemi.com/' directory
"""

import fnmatch
import os
import urllib.request
import zipfile
import hashlib
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy import Column, Integer, String, create_engine, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from intelhex import IntelHex

NRFBase = declarative_base()
engine = create_engine("sqlite:///nRF.db")

class SoftDevice(NRFBase):
    """
    SoftDevice table
    """
    __tablename__ = "SoftDevice"
    soft_id = Column("id", Integer, primary_key=True)
    sdk_version = Column(String(32))
    sign = Column(String(64))
    softdevice_v = Column(String(32))
    nrf = Column(String(32))
    svcalls = relationship("SVCALL")
    svc_rbase = relationship("SVCBase")
    svc_rlast = relationship("SVCLast")
    structs = relationship("Structures")
    mem_addr = relationship("MemoryAddr")

    def __init__(self, sdk_version, softdevice, nrf, header_dir, linker_dir, hex_dir, session):
        """
        SoftDevice Class attributes and methods
        """
        self.sdk_version = sdk_version
        self.softdevice_v = softdevice
        self.nrf = nrf
        self.header_dir = header_dir
        self.linker_dir = linker_dir
        self.hex_dir = hex_dir
        self.sign = None
        self.headers = []
        self.linkers = []
        self.svc_base = dict()
        self.svc_last = dict()
        self.svcs = dict()
        #self.structs = dict()
        self.enum = 0
        self.session = session
    def set_linkers(self):
        """
        Sets the list of linkers'paths of the associated softdevice
        """
        linkers_path = "./SDKs/" + self.sdk_version + "/" + self.linker_dir
        for linker_file in os.listdir(linkers_path):
            if fnmatch.fnmatch(linker_file, "*.ld"):
                self.linkers.append(linkers_path+linker_file)
    def set_headers(self):
        """
        Sets the list of headers'paths to the associated softdevice
        """
        headers_path = "./SDKs/" + self.sdk_version + "/" + self.header_dir
        for header_file in os.listdir(headers_path):
            if fnmatch.fnmatch(header_file, "*.h"):
                #Add the other case
                if "cln" in header_file:
                    self.headers.append(headers_path+header_file)
    def signature(self):
        """
        Returns softdevice's binary's signature
        The signature is the sha256 hash of specific bytes of the firmware
        """
        if (self.hex_dir != None):
            hex_path = "./SDKs/"+ self.sdk_version + "/" + self.hex_dir
            # Converting ihex to binary format
            print("Converting the firmware from intelHex format to binary")
            ih = IntelHex(hex_path)
            bin_file = hex_path.replace(".hex", ".bin")
            ih.tobinfile(bin_file)
            with open(bin_file, 'rb+') as sdv_hex:
                sdv_hex.seek(4096)
                extract = sdv_hex.read(10000)
                self.sign = hashlib.sha256(extract).hexdigest()
        else:
            self.sign = self.sdk_version + "_" + self.nrf + "_" + self.softdevice_v
    def mem_parser(self):
        """
        Extracts memory mapping of RAM and Flash sections of the binary from linkers files
        """
        softdev_v = None
        for mem_path in self.linkers:
            mem_file = 0
            nrf_props = mem_path.rsplit("/")[-1].rsplit("_")
            print(nrf_props)
            if len(nrf_props) == 4:
                card_version = nrf_props[3].replace(".ld", "")
                if "/Source/templates/gcc/" in mem_path and self.softdevice_v in mem_path:
                    self.nrf = mem_path.split("/")[3]
                    mem_file = 1
                    softdev_v = nrf_props[2]
                elif "/components/softdevice/" in mem_path and "/toolchain/armgcc/armgcc_s" in mem_path and self.softdevice_v in mem_path and "xx" in mem_path:
                    self.nrf = nrf_props[2]
                    mem_file = 1
                    if nrf_props[1].startswith("s"):
                        softdev_v = nrf_props[1]
                elif "/components/toolchain/gcc/gcc_nrf5" in mem_path and "xx" in mem_path and self.softdevice_v in mem_path:
                    self.nrf = nrf_props[1]
                    mem_file = 1
                    if nrf_props[2].startswith("s"):
                        softdev_v = nrf_props[2]
                if mem_file == 1:
                    with open(mem_path, 'r+') as memfile:
                        for line in memfile:
                            if ("FLASH" in line and "ORIGIN" in line and "LENGTH" in line):
                                addr = line.split(":")[1].rsplit(',')
                                for mem_addr in addr:
                                    if "ORIGIN" in mem_addr:
                                        rom_origin = mem_addr.split("=")[1].strip()
                                    elif "LENGTH" in mem_addr:
                                        rom_length = mem_addr.split("=")[1].strip().replace("\n", "")
                            if ("RAM" in line and "ORIGIN" in line and "LENGTH" in line):
                                addr = line.split(":")[1].rsplit(',')
                                for mem_addr in addr:
                                    if "ORIGIN" in mem_addr:
                                        ram_origin = mem_addr.split("=")[1].strip()
                                    elif "LENGTH" in mem_addr:
                                        ram_length = mem_addr.split("=")[1].strip().replace("\n", "")
                        print("adding ", card_version, self.nrf, self.sign, softdev_v)
                        mem_addr = MemoryAddr(ram_origin, ram_length, rom_origin, rom_length, softdev_v, self.nrf, card_version, self.sign, self.sdk_version)
                        self.session.add(mem_addr)
    def define_nrf(self):
        """
        Finds which NRF is associated to the provided softdevice, and SDK version
        """
        for mem_path in self.linkers:
            nrf_props = mem_path.rsplit("/")[-1].rsplit("_")
            if len(nrf_props) == 4 and 'xx' in nrf_props[3]:
                if "/Source/templates/gcc/" in mem_path and self.softdevice_v in mem_path:
                    self.nrf = mem_path.split("/")[3]
                elif "/components/softdevice/" in mem_path and "/toolchain/armgcc/armgcc_s" in mem_path and self.softdevice_v in mem_path and "xx" in mem_path:
                    self.nrf = nrf_props[2]
                elif "/components/toolchain/gcc/gcc_nrf5" in mem_path and "xx" in mem_path and self.softdevice_v in mem_path:
                    self.nrf = nrf_props[1]
        print("NRF version: {0}".format(self.nrf))

    def svc_parser(self):
        """
        Global parser: Parses SVC ranges, SVCs and SVCALL from SoftDevice development kit
        """
        for h_path in self.headers:
            self.svc_ranges(h_path)
        for h_path in self.headers:
            self.svc_func(h_path)
            self.structures(h_path)
        for h_path in self.headers:
            self.svcall_parse(h_path)

    def svc_ranges(self, headerfile):
        """
        Extracts SVC ranges of the Soft Device 
        Based on parsing SVC_BASE and SVC_LAST from header files
        """
        try:
            if os.path.exists(headerfile):
                with open(headerfile, 'r') as header:
                    for line in header:
                        if "SVC_BASE" in line and "#define" in line:
                            svc_base = line.split("#define ")[1].replace("(", "").replace(")", "").rsplit()
                            self.svc_base[svc_base[0]] = svc_base[1]
                            svc_b = SVCBase(svc_base[0], svc_base[1], self.sign)
                            self.session.add(svc_b)
                        elif "SVC_LAST" in line and "#define" in line:
                            svc_last = line.split("#define ")[1].rsplit()
                            self.svc_last[svc_last[0]] = svc_last[1]
                            svc_l = SVCLast(svc_last[0], svc_last[1], self.sign)
                            self.session.add(svc_l)
                        else:
                            pass
            else:
                print(headerfile, "doesn't exist")
        except IOError as err:
            print("I/O error: {0}".format(err))

    def structures(self, headerfile):
        """
        Extracts structures from header files
        """
        try:
            if os.path.exists(headerfile):
                with open(headerfile, 'r') as header:
                    for line in header:
                        if "typedef struct" in line:
                            args_tmp = []
                            newline = header.readline()
                            if "{" in newline:
                                newline = header.readline()
                            arg = newline
                            while "}" not in newline:
                                #If structure contains another structure or union
                                if ("union" in newline or "struct" in newline):
                                    union_args = []
                                    if "union" in newline:
                                        arg = "union "
                                    elif "struct" in newline:
                                        arg = "struct "
                                    union_line = header.readline()
                                    while "}" not in union_line:
                                        union_line = header.readline()
                                        union_line = union_line.split(";")[0].strip()
                                        union_args.append(union_line)
                                    union_name = union_line.replace("}", "").replace(";", "")
                                    union_args = union_args[:-1]
                                    arg = "union " + union_name + "(" + ','.join(union_args) + ")"
                                    args_tmp.append(arg)
                                    newline = header.readline()
                                else:
                                    arg = newline.replace(";", "").strip()
                                    args_tmp.append(arg)
                                    newline = header.readline()
                            struct_name = newline.replace("} ", "").replace("\n", "").replace(";", "")
                            structure = Structures(self.sign, struct_name, None, None)
                            self.session.add(structure)
                            for arg in args_tmp:
                                argument = StructArgs(self.sign, arg, struct_name)
                                self.session.add(argument)
        except IOError as err:
            print("I/O error: {0}".format(err))

    def svcall_parse(self, headerfile):
        """
        Parses SVCALL from header files
        Instantiates SVCALL objects with SVCs'syscall number, function name and prototype
        """
        try:
            if os.path.exists(headerfile):
                with open(headerfile, 'r') as header:
                    header.readline()
                    for line in header:
                        if "SVCALL(" in line:
                            svc = line.split(",")[0].split("(")[1].strip()
                            if svc == "number":
                                pass
                            else:
                                func_name = line.split(",")[2].split("(")[0].strip()
                                return_type = line.split(",")[1]
                                #SVCALL(svc, ret_type, prototype) defined on one line
                                if "));" in line:
                                    func_args = line.split("(")[2].replace("));", "").replace("\n", "")
                                #SVCALL defined on multiple lines
                                else:
                                    newline = header.readline()
                                    while "));" not in newline:
                                        newline = header.readline()
                                    func_args = newline.replace("));", "").replace("\n", "")
                                if svc in self.svcs.keys():
                                    svcall = SVCALL(svc, self.svcs[svc], func_name, return_type, func_args, self.sign)
                                    self.session.add(svcall)
                                else:
                                    print("else condition", svc, self.svcs, headerfile)
                                    pass
        except IOError as err:
            print("I/O error: {0}".format(err))

    def svc_func(self, headerfile):
        """
        Parses svcs from header files and calculates associated the svc number
        Result is stored in self.svcs dict
        """
        try:
            if os.path.exists(headerfile):
                with open(headerfile, 'r') as header:
                    previous = header.readline()
                    for line in header:
                        if "_SVCS" in line and "enum" in line:
                            #parse SVCs from file
                            header.readline()
                            self.enum = 1
                            i = 0
                            while 1:
                                enumline = header.readline()
                                if (not("};" in enumline) and self.enum == 1):
                                    svc_func = enumline.split(",")[0].strip()
                                    # Get the SVC_BASE number
                                    if "=" in svc_func:
                                        svc_base = svc_func.split("=")[1].strip()
                                        svc_func = svc_func.split("=")[0].strip()
                                    if svc_base in self.svc_base.keys():
                                        svc_numbase = self.svc_base[svc_base]
                                        if "0x" in svc_numbase:
                                            svc_num = hex(int(svc_numbase, 16)+i)
                                            self.svcs[svc_func] = svc_num
                                        i += 1
                                    #special parsing for BLE_GAP_SVC_BASE + i  in header files
                                    elif " + " in svc_base:
                                        svc_sbase = svc_base.split(" + ")[0].strip()
                                        j = int(svc_base.split(" + ")[1].strip())
                                        if svc_sbase in self.svc_base.keys():
                                            svc_numbase = self.svc_base[svc_sbase]
                                            if "0x" in svc_numbase:
                                                svc_num = hex(int(svc_numbase, 16)+j)
                                                self.svcs[svc_func] = svc_num
                                else:
                                    self.enum = 0
                                    break
                        #special parsing for ant_interface.h, ANT Stack API SVC numbers enumeration
                        elif "ant_interface.h" in headerfile and "enum" in line:
                            self.enum = 1
                            i = 0
                            while 1:
                                enumline = header.readline()
                                if "};" not in enumline and self.enum == 1:
                                    if "," in enumline:
                                        svc_func = enumline.split(",")[0].strip()
                                        if "=" in svc_func:
                                            svc_base = svc_func.split("=")[1].strip()
                                            svc_func = svc_func.split("=")[0].strip()
                                        if svc_base in self.svc_base.keys():
                                            svc_numbase = self.svc_base[svc_base]
                                            if "0x" in svc_numbase:
                                                svc_num = hex(int(svc_numbase, 16)+i)
                                                self.svcs[svc_func] = svc_num
                                            i += 1
                                else:
                                    self.enum = 0
                                    break
                        #redefinitions of the SVC numbers used by the NRF Radio Disable implementation
                        elif "#define" in line and ("SD_RADIO_REQUEST" in line or "SD_RADIO_SESSION_OPEN" in line or "SD_RADIO_SESSION_CLOSE" in line):
                            svc_radio = line.split("#define ")[1].replace("(", "").replace(")", "").rsplit()
                            svc = svc_radio[0]
                            svc_num = svc_radio[1]
                            self.svcs[svc] = svc_num
                        else:
                            pass
        except IOError as err:
            print("I/O error: {0}".format(err))

class MemoryAddr(NRFBase):
    """MemoryAddr table"""
    __tablename__ = "MemoryAddr"
    mem_id = Column("id", Integer, primary_key=True)
    softdev_v = Column(String(64))
    nrf = Column(String(12))
    card_version = Column(String(64))
    ram_origin = Column(String(256))
    ram_length = Column(String(256))
    rom_origin = Column(String(256))
    rom_length = Column(String(256))
    sdk_version = Column(String(256))
    softdev_signature = Column(String(64), ForeignKey('SoftDevice.sign'))
    #__table_args__ = (UniqueConstraint('softdev_v', 'nrf', 'card_version', name='_memory_map'),)
    def __init__(self, ram_origin, ram_length, rom_origin, rom_length, softdev_v, nrf, card_version, softdev_signature, sdk_version):
        """
        Memory Addresses class
        """
        self.ram_origin = ram_origin
        self.ram_length = ram_length
        self.rom_origin = rom_origin
        self.rom_length = rom_length
        self.softdev_v = softdev_v
        self.nrf = nrf
        self.card_version = card_version
        self.softdev_signature = softdev_signature
        self.sdk_version = sdk_version

class SVCALL(NRFBase):
    """SVCALL table"""
    __tablename__ = "SVCALL"
    svc_id = Column("id", Integer, primary_key=True)
    svc = Column(String(64))
    syscall = Column(String(12))
    function = Column(String(64))
    ret_type = Column(String(48))
    arguments = Column(String(256))
    softdev_signature = Column(String(64), ForeignKey('SoftDevice.sign'))
    #__table__args = (UniqueConstraint('svc','softdev_signature', name='_svc_unique_softdev'), )
    def __init__(self, svc, syscall, function, ret_type, arguments, softdev_signature):
        """
        SVCALL class
        """
        self.function = function
        self.svc = svc
        self.syscall = syscall
        self.ret_type = ret_type
        self.arguments = arguments
        self.softdev_signature = softdev_signature

class SVCBase(NRFBase):
    """SVCBast class svc_base ranges for nRF5 version"""
    __tablename__ = "SVCBase"
    id = Column("id", Integer, primary_key=True)
    svc_base_name = Column(String(96))
    svc_base_num = Column(String(96))
    softdev_signature = Column(String(64), ForeignKey('SoftDevice.sign'))
    #__table__args = (UniqueConstraint('svc_base_name','softdev_signature', name='_svcbase_unique_softdev'), )
    """SVC ranges Class"""
    def __init__(self, svc_base, svc_base_num, soft_sign):
        self.svc_base_name = svc_base
        self.svc_base_num = svc_base_num
        self.softdev_signature = soft_sign

class StructArgs(NRFBase):
    """Structures' arguments table"""
    __tablename__ = "StructArgs"
    arg_id = Column("id", Integer, primary_key=True)
    arg_name = Column(String(96))
    struct_name = Column(String(96), ForeignKey('Structures.name'))
    softdev_signature = Column(String(64), ForeignKey('SoftDevice.sign'))
    def __init__(self, soft_sign, arg_name, struct_name):
        self.arg_name = arg_name
        self.struct_name = struct_name
        self.softdev_signature = soft_sign

class UnionParams(NRFBase):
    """Structure UnionParams of union members contained in structures"""
    __tablename__ = "UnionParams"
    union_id = Column("id", Integer, primary_key=True)
    union_param = Column(String(96))
    union_name = Column(String(96), ForeignKey('StructArgs.arg_name'))
    struct_name = Column(String(96), ForeignKey('Structures.name'))
    softdev_signature = Column(String(64), ForeignKey('SoftDevice.sign'))
    def __init__(self, soft_sign, param, union, struct):
        self.union_param = param
        self.union_name = union
        self.struct_name = struct
        self.softdev_signature = soft_sign

class Structures(NRFBase):
    """Structures table"""
    __tablename__ = "Structures"
    struct_id = Column("id", Integer, primary_key=True)
    name = Column(String(96))
    contains_union = Column(String(10)) #bool
    contains_struct = Column(String(10)) #bool
    softdev_signature = Column(String(64), ForeignKey('SoftDevice.sign'))
    def __init__(self, soft_sign, name, contains_union, contains_struct):
        self.name = name
        self.softdev_signature = soft_sign

class SVCLast(NRFBase):
    """SVCLast class svc_last ranges for nRF5 version"""
    __tablename__ = "SVCLast"
    id = Column("id", Integer, primary_key=True)
    svc_last_name = Column(String(96))
    svc_last_num = Column(String(96))
    softdev_signature = Column(String(64), ForeignKey('SoftDevice.sign'))
    #__table__args = (UniqueConstraint('svc_last_name','softdev_signature', name='_svclast_unique_softdev'), )
    """SVC ranges Class"""
    def __init__(self, svc_last, svc_last_num, soft_sign):
        self.svc_last_name = svc_last
        self.svc_last_num = svc_last_num
        self.softdev_signature = soft_sign

class SDK(object):
    """
    Based on the Nordic development kit archive in its zip format. 
    The version will identify the SDK.
    The softdevices contained in this version are identified and listed, and for each softdevice, 
    headers and linkers files are extracted from the archive to the disk into the local
    directory SDKs/sdk_version/. If found in the archive, the firmware in its .hex format 
    associated to the softdevice is also extracted.
    """
    def __init__(self, sdk_version, sdk_path):
        self.version = sdk_version
        self.zip_path = sdk_path
        self.compiled = None
        self.hex_path = None

    def list_softdevices(self):
        """
        Lists Softdevices contained in the SDK archive
        """
        sdv = "components/softdevice/s"
        inc_path = "/Include/s"
        src_path = "/Source/templates/gcc/"
        soft_devices = set()
        with zipfile.ZipFile(self.zip_path) as sdv_zip:
            for f in sdv_zip.namelist():
                #compiled soft_device
                if (f.startswith(sdv) and f.endswith('/')):
                    soft_devices.add(f.split("/")[2])
                    #only soft_device source code
                elif (f.startswith("nrf") and inc_path in f and len(f.split("/")[2]) == 4 and f.split("/")[2].startswith('s')):
                    nrf = f.split("/")[0]
                    soft_devices.add(nrf + ","+ f.split("/")[2])
        return soft_devices
    def extract_softdevices(self):
        """
        Extracts headers and ld directories from archive to local disk
        """
        sdv = "components/softdevice/s"
        inc_path = "/Include/s"
        src_path = "/Source/templates/gcc/"
        with zipfile.ZipFile(self.zip_path) as sdv_zip:
            for f in sdv_zip.namelist():
                #compiled soft_device
                if f.startswith(sdv) and f.endswith("/"):
                    if ("headers" in f and not "nrf5" in f) or ("toolchain/armgcc/" in f):
                        dir_to_extract = f 
                        self.extract_fromzip(sdv_zip, f)
                #for archives containing only soft_device source code 
                elif f.startswith("nrf5"):
                    if (inc_path in f and len(f.split("/")[2]) == 4 and f.split("/")[2].startswith('s')) or (src_path in f and "xx" in f and "_s" in f):
                        self.extract_fromzip(sdv_zip, f)
    def extract_hex(self, hex_path):
        """
        Extracts header and linker files from the SDK archive to local SDKs directory
        """
        directory = "./SDKs/" + self.version + "/"
        if not os.path.exists(directory):
            if not os.path.exists("SDKs"):
                os.mkdir("SDKs")
            os.mkdir(directory)
        with zipfile.ZipFile(self.zip_path) as sdv_zip:
            for f in sdv_zip.namelist():
                if (f.startswith(hex_path) and fnmatch.fnmatch(f, '*.hex')):
                    print("Extracting the Hex format of firmware from archive to disk")
                    self.hex_path = f
                    sdv_zip.extract(f, directory)
    def extract_fromzip(self, sdv_zip, path):
        """
        Extracts header and ld files from the SDK archive to local SDKs directory
        """
        directory = "./SDKs/" + self.version + "/"
        if not os.path.exists(directory):
            if not os.path.exists("SDKs"):
                os.mkdir("SDKs")
            os.mkdir(directory)
        try:
            for f in sdv_zip.namelist():
                if f.startswith(path):
                    sdv_zip.extract(f, directory)
        except IOError:
            print("I/O error: {0}".format(err))

class SDKs(object):
    """Nordic development kits"""
    def __init__(self, directory):
        """
        creates a dict of SDK versions associated to SDK archives contained in the given directory
        """
        try:
            self.dict = dict()
            self.dir = directory
            print("Listing zip files from nRF5_SDK directory: ", self.dir)
            for curdir, subdir, myfile in os.walk(directory):
                for fname in myfile:
                    if "zip" in fname:
                        sdk_version = '.'.join(fname.split("_", 2)[2].split(".zip")[0].split("_")[:-1])
                        zip_path = os.path.join(curdir, fname)
                        self.dict[sdk_version] = zip_path
        except IOError:
            print("I/O error: {0}".format(err))


def download_sdk(path: str, url: str):
    html_page = urllib.request.urlopen(url)
    soup = BeautifulSoup(html_page, "html.parser")
    sdk_version_links = set()
    for link in soup.findAll('a'):
        href_link = str(link.get('href'))
        if href_link.startswith("nRF5") and "SDK" in href_link:
            sdk_version_links.add(href_link)
            Path(os.path.join(path, href_link)).mkdir(parents=True, exist_ok=True)

    for sdk_version_path in sdk_version_links:
        print(f'Checking for SDKs {sdk_version_path}')
        html_page = urllib.request.urlopen(url + sdk_version_path)
        soup = BeautifulSoup(html_page, "html.parser")
        processed_sdk = set()
        for link in soup.findAll('a'):
            href_link = str(link.get('href'))
            if href_link in processed_sdk:
                continue
            if href_link.lower().startswith("nrf5") and "sdk" in href_link.lower() \
                    and ".zip" in href_link and "doc" not in href_link and "packs" not in href_link:
                zip_file_path = os.path.join(path, sdk_version_path, href_link)
                if os.path.isfile(zip_file_path):
                    processed_sdk.add(href_link)
                    continue
                print(f'Downloading {href_link}')
                urllib.request.urlretrieve(url + sdk_version_path + href_link,
                                           os.path.join(path, sdk_version_path, href_link))
                processed_sdk.add(href_link)


def main():
    """
    main
    """
    Session = sessionmaker(bind=engine)
    session = Session()
    NRFBase.metadata.create_all(engine)
    sdk_dir = "developer.nordicsemi.com/nRF5_SDK/"
    download_sdk(sdk_dir, "http://" + sdk_dir)
    sdks = SDKs(sdk_dir)
    for sdk_v, zip_path in sdks.dict.items():
        sdk = SDK(sdk_v, zip_path)
        print("\n       ====================")
        print("       ", sdk_v, "=>", zip_path)
        print("        ====================")
        sdk.extract_softdevices()
        soft_devices = list(sdk.list_softdevices())
        for soft_dvc in soft_devices:
            if "nrf" in soft_dvc:
                nrf = soft_dvc.split(",")[0]
                sdvc = soft_dvc.split(",")[1]
                if sdk_v == "4.4.2":
                    header_dir = nrf + "/Include/"
                else:
                    header_dir = nrf + "/Include/" + sdvc +"/"
                linker_dir = nrf + "/Source/templates/gcc/"
                hex_dir = None
                print("\n=== {0} {1} ===".format(sdvc, nrf))
                print("Hex file for {0} not found in archive. Firmware's signature will depend on the strings contained in the given binary".format(sdvc))
            else:
                nrf = "hex" 
                sdvc = soft_dvc
                header_dir = "components/softdevice/" + sdvc + "/headers/"
                linker_dir = "components/softdevice/" + sdvc + "/toolchain/armgcc/"
                linkers_path = "./SDKs/" + sdk_v + "/" + linker_dir
                if os.path.exists(linkers_path) is False:
                    linker_dir = "components/toolchain/gcc/"
                hex_dir = "components/softdevice/" + sdvc + "/hex/"
                print("\n=== {0} {1} ===".format(sdvc, nrf))
                sdk.extract_hex(hex_dir)
            soft_device = SoftDevice(sdk_v, sdvc, nrf, header_dir, linker_dir, sdk.hex_path, session)
            soft_device.signature()
            print("SoftDevice Signature: {0}".format(soft_device.sign))
            soft_device.set_headers()
            # Setting a list of header files for parsing
            try:
                soft_device.set_linkers()
                if soft_device.linkers != []:
                    soft_device.mem_parser()
            except IOError as err:
                print("I/O error: {0}".format(err))
            soft_device.svc_parser()
            print("SVCALLs, functions, structures' parsing completed")
            session.add(soft_device)
    session.commit()
    print("SoftDevice successfully added to database")

if __name__ == '__main__':
    main()
